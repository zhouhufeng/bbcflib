# Built-in modules #
import re, tarfile

# Internal modules #
from bbcflib.common import unique_filename_in

# Other modules #
from bein import program


def untar_genome_fasta(assembly, convert=True):
    """Untar (genome) fasta files.

    :param assembly: the GenRep.Assembly instance of the species of interest.
    :param convert: (bool) True if chromosome names need conversion RefSeq -> Ensembl, 
        False otherwise.
    """
    if convert:
        chrlist = dict((str(k[0])+"_"+str(k[1])+"."+str(k[2]),v['name'])
                       for k,v in assembly.chromosomes.iteritems())
    else:
        chrlist = {}
    archive = tarfile.open(assembly.fasta_path())
    genomeRef = {}
    for f in archive.getmembers():
        if f.isdir(): continue
        inf = archive.extractfile(f)
        header = inf.readline()
        headpatt = re.search(r'>(\S+)\s',header)
        if headpatt: chrom = headpatt.groups()[0]
        else: continue
        if chrom in chrlist:
            header = re.sub(chrom,chrlist[chrom],header)
            chrom = chrlist[chrom]
        genomeRef[chrom] = unique_filename_in()
        with open(genomeRef[chrom],"wb") as outf:
            outf.write(header)
            [outf.write(l) for l in inf]
        inf.close()
    archive.close()
    return genomeRef

@program
def sam_pileup(assembly,bamfile,refGenome,via='lsf'):
    """Launches 'samtools pileup' on command-line.
    
    :param assembly: Genrep.Assembly object for the species of interest.
    :param bamfile: path to the BAM file to run the samtool pileup command on.
    :param refGenome: path to the species' reference genome (fasta file).
    """
    if str(assembly.name) in ['MLeprae_TN','MSmeg_MC2_155','MTb_H37Rv','NA1000','TB40-BAC4']:
        ploidy=1
        minSNP=10
        minCoverage=80
    else:
        ploidy=2
        minSNP=20
        minCoverage=40
    return {"arguments": ["samtools","pileup","-B","-cvsf",refGenome,"-N",str(ploidy),bamfile],
            "return_value": [minCoverage,minSNP]}

def parse_pileupFile(dictPileupFile,allSNPpos,chrom,minCoverage=80,minSNP=10):
    """ ..., produces a file containing
    quantification and localization of SNPs.

    :param ex: a bein.Execution instance.
    :param dictPileupFile: (dict) ?
    :param allSNPPos: (dict) ?
    :param chrom: (str) chromosome name.
    :param minCoverage: (int) ?
    :param minSNP: (int) ?
    """
    formatedPileupFilename=unique_filename_in()
    allSample={}
    iupac={'M':['A','a','C','c'],'Y':['T','t','C','c'],'R':['A','a','G','g'],
           'S':['G','g','C','c'],'W':['A','a','T','t'],'K':['T','t','G','g']}

    for p,sname in dictPileupFile.iteritems():
        cpt=0
        allpos = sorted(allSNPpos.keys(),reverse=True)
        position = -1
        allSample[sname]={}
        with open(p) as sample:
            for line in sample:
                info=line.split("\t")
                while int(info[1])>position:
                    if not(allpos): break
                    position = allpos.pop()
                    allSample[sname][position]="-"
                if not(int(info[1]) == position): continue
                if int(info[7])<minSNP:
                    string="* "
                else:
                    string=""
                if re.search(r'[ACGT]',info[3]):
                    string+=info[3]
                    allSample[sname][position]=string
                else:
                    snp=0
                    snp2=0
                    snp=info[8].count(iupac[info[3]][0])+info[8].count(iupac[info[3]][1])
                    snp2=info[8].count(iupac[info[3]][2])+info[8].count(iupac[info[3]][3])
                    if (snp+snp2)*100 > minCoverage*int(info[7]):
                        cov = 100/float(info[7])
                        if info[2] == iupac[info[3]][0]:
                            allSample[sname][position]=string+"%.4g%% %s / %.4g%% %s" \
                                    %(snp2*cov,iupac[info[3]][2],100-snp2*cov,iupac[info[3]][0])
                        elif info[2] == iupac[info[3]][2]:
                            allSample[sname][position]=string+"%.4g%% %s / %.4g%% %s" \
                                    %(snp*cov, iupac[info[3]][0],100-snp*cov, iupac[info[3]][2])
                        else:
                            allSample[sname][position]=string+"%.4g%% %s / %.4g%% %s" \
                                    %(snp*cov, iupac[info[3]][0],    snp2*cov,iupac[info[3]][2])
            while allpos:
                position = allpos.pop()
                allSample[sname][position]="-"

    firstSample=allSample.values()[0]
    with open(formatedPileupFilename,'w') as outfile:
        outfile.write("chromosome\tposition\treference\t"+"\t".join(dictPileupFile.values())+"\n")
        for p in sorted(firstSample):
            nbNoSnp=0
            for s in allSample:
                nbNoSnp+=allSample[s][p].count("-")
            if nbNoSnp!=len(allSample.keys()):
                outfile.write("\t".join([chrom,str(p),allSNPpos[p]]+[allSample[s][p] for s in allSample])+"\n")

    return formatedPileupFilename

def synonymous(job,allSnp):
    """Writes the first line of the file *allSnp* to the file *allCodon* (??)

    :param job: a Frontend.Job object.
    :param allSnp: path to the file summarizing the localization of SNPs.
    """
    allCodon=unique_filename_in()
    file=open(allSnp,'rb')
    outfile=open(allCodon,'wb')
    outfile.write(file.readline())
    return allCodon


def posAllUniqSNP(PileupFile,minCoverage=80):
    """ 
    :param PileupFile: (dict) dictionary of the form {filename: [?, bein.Future]} 
    :param minCoverage: (int) 
    """
    d={}
    for p,v in PileupFile.iteritems():
        parameters=v[1].wait()
        PileupFile[p]=v[0]
        with open(p) as f:
            for l in f:
                data=l.split("\t")
                cpt=data[8].count(".")+data[8].count(",")
                if cpt*100 < int(data[7])*int(minCoverage) and int(data[7])>9:
                    d[int(data[1])]=data[2]
    return (d,parameters)

