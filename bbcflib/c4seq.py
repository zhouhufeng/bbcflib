"""
=======================
Module: bbcflib.c4seq
=======================

This module provides functions to run a 4c-seq analysis
from reads mapped on a reference genome.

"""

import sys, os, json, re, tarfile, time
from bein import program
from bein.util import touch
from bbcflib.createlib import get_libForGrp
from bbcflib.track import track, convert
from bbcflib.mapseq import parallel_density_sql
from bbcflib.common import unique_filename_in, gzipfile, merge_sql, cat, gfminer_run, set_file_descr

# *** Create a dictionary with infos for each primer (from file primers.fa)
# ex: primers_dict=loadPrimers('/archive/epfl/bbcf/data/DubouleDaan/finalAnalysis/XmNGdlXjqoj6BN8Rj2Tl/primers.fa')
def loadPrimers(primersFile):
    '''Create a dictionary with infos for each primer (from file primers.fa) '''
    primers = {}
    name = ''
    with open(primersFile,'rb') as f:
        for s in f:
            s = re.sub(r'\s','',s)
            if not(s): continue
            if not(re.search(r'^>',s)):
                if name:
                    primers[name]['seq']=s
                    name = ''
                continue
            infos = s.split('|')
            name = infos[0][1:]
            primerInfos = { 'fullseq': infos[1],
                            'baitcoord': infos[2],
                            'primary': infos[3],
                            'seq': '' }
            if re.search('Exclude',infos[-1]):
                primerInfos['regToExclude'] = infos[-1].split('=')[1]
            primerInfos['seqToFilter'] = infos[4:-1]
            if not name in primers: primers[name] = primerInfos
    return primers

@program
def segToFrag( countsPerFragFile, regToExclude="", script_path='' ):
    '''
    This function calls segToFrag.awk (which transforms the counts per segment to a normalised count per fragment).
    Provide a region to exclude if needed.
    '''
    args = ["awk","-f",os.path.join(script_path,'segToFrag.awk')]
    if regToExclude: args += ["-v","reg2Excl="+regToExclude]
    return {'arguments': args+[countsPerFragFile], 'return_value': None}

def _RCMD(path,script):
    return ["R","--vanilla","--slave","-f",os.path.join(path,script),"--args"]

@program
def profileCorrection( inputFile, baitCoord, name, outputFile, reportFile, script_path='' ):
    time.sleep(20)
    args = _RCMD(script_path,"profileCorrection.R")+[inputFile,baitCoord,name,outputFile,reportFile]
    return {'arguments': args, 'return_value': None}

@program
def smoothFragFile( inputFile, nFragsPerWin, curName, outputFile, regToExclude="", script_path='' ):
    args = _RCMD(script_path,"smoothData.R")+[inputFile,str(nFragsPerWin),curName,outputFile,regToExclude]
    return {'arguments': args, 'return_value': None}

@program
def runDomainogram( infile, name, prefix=None, regCoord="",
                    wmaxDomainogram=500, wmax_BRICKS=50, skip=0, script_path='' ):
    time.sleep(60)
    if prefix is None: prefix = name
    args = _RCMD(script_path,"runDomainogram.R")+[infile,name,prefix,regCoord,str(wmaxDomainogram),str(wmax_BRICKS),str(skip),script_path]
    return {'arguments': args, 'return_value': prefix+".log"}


def density_to_countsPerFrag( ex, file_dict, groups, assembly, regToExclude, script_path, via='lsf' ):
    '''
    Main function to compute normalised counts per fragments from a density file.
    '''
    futures = {}
    results = {}
    for gid, group in groups.iteritems():
        density_file = file_dict['density'][gid]
        reffile = file_dict['lib'][gid]
#   scores = track(density_file)
        gm_futures = []
        for ch in assembly.chrnames:
            chref = os.path.join(reffile,ch+".bed.gz")
            if not(os.path.exists(chref)): chref = reffile
#            features = track(chref,'bed')
#            outbed.write(gMiner.stream.mean_score_by_feature(
#                    scores.read(selection=ch),
#                    features.read(selection=ch)), mode='append')
            bedfile = unique_filename_in()+".bed"
            gfminer_job = {"operation": "score_by_feature",
                           "output": bedfile,
                           "datatype": "qualitative",
                           "args": "'"+json.dumps({"trackScores":density_file,
                                                   "trackFeatures":chref,
                                                   "chromosome":ch})+"'"}
            gm_futures.append((gfminer_run.nonblocking(ex,gfminer_job,via=via),
                               bedfile))
        outsql = unique_filename_in()+".sql"
        sqlouttr = track( outsql, chrmeta=assembly.chrmeta,
                          info={'datatype':'quantitative'},
                          fields=['start', 'end', 'score'] )
        outbed_all = []
        for n,f in enumerate(gm_futures):
            f[0].wait()
            fout = f[1]
            if not(os.path.exists(fout)):
                time.sleep(60)
                touch(ex,fout)
            outbed_all.append(fout)
            outbed = track(fout, chrmeta=assembly.chrmeta)
            sqlouttr.write( outbed.read(fields=['start', 'end', 'score'],
                                        selection={'score':(0.01,sys.maxint)}),
                            chrom=assembly.chrnames[n] )
        sqlouttr.close()
        countsPerFragFile = unique_filename_in()+".bed"
        countsPerFragFile = cat(outbed_all,out=countsPerFragFile)
        results[gid] = [ countsPerFragFile, outsql ]
        FragFile = unique_filename_in()
        touch(ex,FragFile)
        futures[gid] = (FragFile,
                        segToFrag.nonblocking( ex, countsPerFragFile, regToExclude[gid],
                                               script_path, via=via, stdout=FragFile ,
                                               memory=4 ))
    def _parse_select_frag(stream):
        for s in stream:
            sr = s.strip().split('\t')
            if re.search(r'IsValid',sr[2]) \
                    and not(re.search(r'_and_',sr[8]) or re.search(r'BothRepeats',sr[8]) or re.search(r'notValid',sr[8])):
                patt = re.search(r'([^:]+):(\d+)-(\d+)',sr[1])
                if patt:
                    coord = patt.groups()
#                    if float(sr[11])>0.0:
                    yield (coord[0], int(coord[1])-1, int(coord[2]), float(sr[11]))
    for gid, res in futures.iteritems():
        res[1].wait()
        touch(ex,res[0])
        segOut = open(res[0],"r")
        resBedGraph = unique_filename_in()+".sql"
        sqlTr = track( resBedGraph, fields=['start','end','score'],
                       info={'datatype':'quantitative'}, chrmeta=assembly.chrmeta )
        sqlTr.write(_parse_select_frag(segOut),fields=['chr','start','end','score'])
        sqlTr.close()
        segOut.close()
        results[gid].extend([res[0],resBedGraph])
    return results #[countsPerFrag_allBed, countsPerFrag_selectSql, segToFrag_out, segToFrag_sql]

############################################################################
def c4seq_workflow( ex, job, primers_dict, assembly,
                    c4_url=None, script_path='', logfile=sys.stdout, via='lsf' ):
    '''
    Main
    * open the 4C-seq minilims and create execution
    * 0. get/create the library
    * 1. if necessary, calculate the density file from the bam file (mapseq.parallel_density_sql)
    * 2. calculate the count per fragment for each denstiy file with gfminer:score_by_feature to calculate)
    '''
    mapseq_files = job.files
### outputs
    processed = {'lib': {}, 'density': {}, '4cseq': {}}
    regToExclude = {}
    new_libs=[]
### options
    run_domainogram = {}
    before_profile_correction = {}
### do it
    for gid, group in job.groups.iteritems():
        run_domainogram[gid] = group.get('run_domainogram',False)
        if isinstance(run_domainogram[gid],basestring):
            run_domainogram[gid] = (run_domainogram[gid].lower() in ['1','true','on','t'])
        before_profile_correction[gid] = group.get('before_profile_correction',False)
        if isinstance(before_profile_correction[gid],basestring):
            before_profile_correction[gid] = (before_profile_correction[gid].lower() in ['1','true','on','t'])
        processed['lib'][gid] = get_libForGrp(ex, group, assembly,
                                              new_libs, gid, c4_url, via=via)
#reffile='/archive/epfl/bbcf/data/DubouleDaan/library_Nla_30bps/library_Nla_30bps_segmentInfos.bed'
        density_files = []
        regToExclude[gid] = primers_dict.get(group['name'],{}).get('regToExclude',"").replace('\r','')
        for rid,run in group['runs'].iteritems():
            libname = mapseq_files[gid][rid]['libname']
            if job.options.get('merge_strands') != 0 or not('wig' in mapseq_files[gid][rid]):
                density_file=parallel_density_sql( ex, mapseq_files[gid][rid]['bam'],
                                                   assembly.chrmeta,
                                                   nreads=mapseq_files[gid][rid]['stats']["total"],
                                                   merge=0,
                                                   read_extension=mapseq_files[gid][rid]['stats']['read_length'],
                                                   convert=False,
                                                   via=via )
                density_file += "merged.sql"
                ex.add( density_file,
                        description=set_file_descr("density_file_"+libname+".sql",
                                                   groupId=gid,step="density",type="sql",view='admin',gdv="1") )
            else:
                density_file = mapseq_files[gid][rid]['wig']['merged']
            density_files.append(density_file)
        # back to grp level!
        processed['density'][gid] = merge_sql(ex, density_files, via=via)

    processed['4cseq'] = {'countsPerFrag': density_to_countsPerFrag( ex, processed, job.groups, assembly,
                                                                     regToExclude, script_path, via ),
                          'profileCorrection': {}, 'smoothFrag': {}, 'domainogram': {}}
    futures = {}
    for gid, group in job.groups.iteritems():
        file1 = unique_filename_in()
        touch(ex,file1)
        file2 = unique_filename_in()
        touch(ex,file2)
        file3 = unique_filename_in()
        touch(ex,file3)
        nFragsPerWin = group['window_size']
        resfile = unique_filename_in()+".bedGraph"
        convert(processed['4cseq']['countsPerFrag'][gid][3],resfile)
        time.sleep(20)
        touch(ex,resfile)
        futures[gid] = (profileCorrection.nonblocking( ex, resfile,
                                                       primers_dict[group['name']]['baitcoord'],
                                                       group['name'], file1, file2, script_path,
                                                       via=via ),
                        smoothFragFile.nonblocking( ex, resfile, nFragsPerWin, group['name'],
                                                    file3, regToExclude[gid], script_path, via=via, memory=4 ))
        processed['4cseq']['profileCorrection'][gid] = [file1,file2,resfile]
        processed['4cseq']['smoothFrag'][gid] = [file3]
    futures2 = {}
    for gid, f in futures.iteritems():
        profileCorrectedFile = processed['4cseq']['profileCorrection'][gid][0]
        bedGraph = processed['4cseq']['profileCorrection'][gid][2]
        f[0].wait()
        nFragsPerWin = job.groups[gid]['window_size']
        grName = job.groups[gid]['name']
        file4 = unique_filename_in()
        touch(ex,file4)
        processed['4cseq']['smoothFrag'][gid].append(file4)
        futures2[gid] = (smoothFragFile.nonblocking( ex, profileCorrectedFile, nFragsPerWin, grName+"_fromProfileCorrected",
                                                     file4, regToExclude[gid], script_path, via=via, memory=4 ), )
        if run_domainogram[gid]:
            regCoord = regToExclude[gid] or primers_dict[grName]['baitcoord']
            if before_profile_correction[gid]:
                futures2[gid] += (runDomainogram.nonblocking( ex, bedGraph, grName, regCoord=regCoord,
                                                              script_path=script_path, via=via, memory=15 ), )
            else:
                futures2[gid] += (runDomainogram.nonblocking( ex, profileCorrectedFile, grName,
                                                              regCoord=regCoord.split(':')[0], skip=1,
                                                              script_path=script_path, via=via, memory=15 ), )
    for gid, f in futures2.iteritems():
        futures[gid][1].wait()
        f[0].wait()
        if len(f)>1:
            resFiles = []
            logFile = f[1].wait()
            start = False
            tarname = job.groups[gid]['name']+"_domainogram.tar.gz"
            res_tar = tarfile.open(tarname, "w:gz")
            if logFile is None: continue
            with open(logFile) as f:
                for s in f:
                    s = s.strip()
                    if re.search('####resfiles####',s):
                        start = True
                    elif start and not re.search("RData",s):
                        resFiles.append(s)
                        res_tar.add(s)
            res_tar.close()
            processed['4cseq']['domainogram'][gid] = resFiles+[tarname]

################ Add everything to minilims below!
    step = "density"
    for gid, sql in processed['density'].iteritems():
        fname = "density_file_"+job.groups[gid]['name']+"_merged"
        ex.add( sql, description=set_file_descr( fname+".sql",
                                                 groupId=gid,step=step,type="sql",gdv="1" ) )
        wig = unique_filename_in()+".bw"
        convert( sql, wig )
        ex.add( wig, description=set_file_descr( fname+".bw",
                                                 groupId=gid,step=step,type="bigWig",ucsc="1") )
    step = "norm_counts_per_frag"
    for gid, resfiles in processed['4cseq']['countsPerFrag'].iteritems():
        fname = "meanScorePerFeature_"+job.groups[gid]['name']
        ex.add( resfiles[1], description=set_file_descr( fname+".sql",
                                                         groupId=gid,step=step,type="sql",view="admin",gdv='1'))
        gzipfile(ex,resfiles[0])
        ex.add( resfiles[0]+".gz", description=set_file_descr( fname+".bed.gz",
                                                               groupId=gid,step=step,type="bed",view="admin" ))
        fname = "segToFrag_"+job.groups[gid]['name']
        ex.add( resfiles[3], description=set_file_descr( fname+"_all.sql",
                                                         groupId=gid,step=step,type="sql",
                                                         comment="all informative frags - null included" ))
        trsql = track(resfiles[3])
        bwig = unique_filename_in()+".bw"
        trwig = track(bwig,chrmeta=trsql.chrmeta)
        trwig.write(trsql.read(fields=['chr','start','end','score'],
                               selection={'score':(0.01,sys.maxint)}))
        trwig.close()
        ex.add( bwig, set_file_descr(fname+".bw",groupId=gid,step=step,type="bigWig",ucsc='1'))
    step = "profile_correction"
    for gid, resfiles in processed['4cseq']['profileCorrection'].iteritems():
        profileCorrectedFile = resfiles[0]
        reportProfileCorrection = resfiles[1]
        fname = "segToFrag_"+job.groups[gid]['name']+"_profileCorrected"
        gzipfile(ex,profileCorrectedFile)
        ex.add( profileCorrectedFile+".gz",
                description=set_file_descr(fname+".bedGraph.gz",groupId=gid,step=step,type="bedGraph",ucsc='1',gdv='1'))
        ex.add( reportProfileCorrection, description=set_file_descr(fname+".pdf",
                                                                    groupId=gid,step=step,type="pdf"))
    step = "smoothing"
    for gid, resfiles in processed['4cseq']['smoothFrag'].iteritems():
        smoothFile = resfiles[0]
        afterProfileCorrection = resfiles[1]
        nFrags = str(job.groups[gid]['window_size'])
        fname = "segToFrag_"+job.groups[gid]['name']+"_smoothed_"+nFrags+"FragsPerWin.bedGraph.gz"
        gzipfile(ex,smoothFile)
        ex.add(smoothFile+".gz",
               description=set_file_descr(fname,groupId=gid,step=step,type="bedGraph",ucsc='1',gdv='1'))
        fname = "segToFrag_"+job.groups[gid]['name']+"_profileCorrected_smoothed_"+nFrags+"FragsPerWin.bedGraph.gz"
        gzipfile(ex,afterProfileCorrection)
        ex.add(afterProfileCorrection+".gz",
               description=set_file_descr(fname,groupId=gid,step=step,type="bedGraph",ucsc='1',gdv='1'))
    step = "domainograms"
    for gid, resfiles in processed['4cseq']['domainogram'].iteritems():
        tarFile = resfiles.pop()
        fname = job.groups[gid]['name']+"_domainogram.tar.gz"
        ex.add(tarFile, description=set_file_descr(fname,
                                                   groupId=gid,step=step,type="tgz"))
        for s in resfiles:
            if re.search("bedGraph$",s):
                gzipfile(ex,s)
                s += ".gz"
                ex.add( s, description=set_file_descr( s, groupId=gid,step=step,type="bedGraph",ucsc="1",gdv="1"))
    return processed
