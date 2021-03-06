"""
======================
Module: bbcflib.mapseq
======================

This module provides functions useful to map raw reads using bowtie.
The most common workflow will first use ``map_reads`` which takes the following arguments:

  * ``'ex'``: an execution environment to run jobs in,

  * ``'fastq_file'``: the raw reads as a fastq file,

  * ``'chromosomes'``: a dictionary with keys 'chromosome_id' as used in the bowtie indexes and values a dictionary with usual chromosome names and their lengths,

  * ``'bowtie_index'``: the file prefix to the bowtie index,

  * ``'maxhits'``: the maximum number of hits per read to keep in the output (default *5*),

  * ``'antibody_enrichment'``: an approximate enrichement ratio of protein bound sequences over controls (default *50*),

  * ``'name'``: sample name to be used in descriptions and file names,

  * ``'remove_pcr_duplicates'``: whether to remove probable PCR amplification artifacts based on a Poisson confidence threshold (default *True*),

  * ``'bwt_args'``: a list of specific arguments for bowtie (in addition to ["-Sam",str(max(20,maxhits)),"--best","--strata"]).

The function ``map_groups`` will take a collection of sample as described in a *job* object from the ``frontend`` module and run fetch fastq files for each of them through using a ``daflims`` object, use an 'Assembly' object from ``genrep`` to get the bowtie indexes and run ``map_reads`` for each sample.

The second step in the workflow consists in generating genome-wide density maps with ``densities_groups`` which needs a 'bein' execution environment, the same *job* and *assembly* as above and a dictionary 'file_dict' as returned by ``map_groups``. The function then runs ``parallel_density_sql`` on each 'bam' file to obtain a normalized read density profile as a 'sqlite' file.

Below is the script used by the frontend::

    from bbcflib import daflims, genrep, frontend, gdv, common
    from bbcflib.mapseq import *
    M = MiniLIMS( limspath )
    working_dir = '/path/to/scratch/on/cluster'
    hts_key = 'test_key'
    gl = { 'hts_mapseq': {'url': 'http://htsstation.epfl.ch/mapseq/'},
           'genrep_url': 'http://bbcftools.vital-it.ch/genrep/',
           'bwt_root': '/db/genrep/',
           'script_path': '/srv/chipseq/lib',
           'lims': {'user': 'alice',
                     'passwd': {'lgtf': 'bob123',
                                'gva': 'joe456'}},
            'gdv': {'url': 'http://svitsrv25.epfl.ch/gdv',
                    'email': 'alice.ecila@somewhere.edu',
                    'key': 'xxxxxxxxxxxxxxxxxxxxxxxx'} }
    assembly_id = 'mm9'
    htss = frontend.Frontend( url=gl['hts_mapseq']['url'] )
    job = htss.job( hts_key )
    g_rep = genrep.GenRep( gl['genrep_url'], gl['bwt_root'] )
    assembly = genrep.Assembly( assembly=assembly_id, genrep=g_rep )
    daflims1 = dict((loc,daflims.DAFLIMS( username=gl['lims']['user'],
                                          password=gl['lims']['passwd'][loc] ))
                    for loc in gl['lims']['passwd'].keys())
    with execution( M, description=hts_key, remote_working_directory=working_dir ) as ex:
        job = get_fastq_files( ex, job )
        run_fastqc( ex, job, via=via )
        mapped_files = map_groups( ex, job, assembly )
        pdf = add_pdf_stats( ex, mapped_files,
                             dict((k,v['name']) for k,v in job.groups.iteritems()),
                             gl['script_path'] )
        density_files = densities_groups( ex, job, mapped_files, assembly.chromosomes )
        gdv_project = gdv.new_project( gl['gdv']['email'], gl['gdv']['key'],
                                       job.description, assembly.id, gl['gdv']['url'] )
        add_pickle( ex, gdv_project, description='py:gdv_json' )
    print ex.id
    allfiles = get_files( ex.id, M )
    print allfiles
"""

# Built-in modules #
import sys, os, re, json, shutil, gzip, tarfile, bz2, pickle, urllib, time

# Internal modules #
from bbcflib import frontend, genrep, daflims
from bbcflib.common import cat, set_file_descr, merge_sql, gzipfile, unique_filename_in, fasta_length
from bbcflib import track

# Other modules #
import pysam
from bein import program, ProgramFailed, MiniLIMS
from bein.util import add_pickle, touch, split_file, count_lines

from bbcflib.workflows import _basepath, _arch_basepath
demultiplex_path = os.path.join(_basepath,"demultiplexing_minilims.files/")

###############
# Fastq files
###############
@program
def fastq_dump(filename, options=None):
    """
    Binds ``fastq-dump`` to convert *sra* (short reads archive) to *fastq* format.
    If ``--split-files`` is given as option, the return value is a pair *(read_1.fastq,read_2.fastq)*.
    """
    if not isinstance(options,list): options = []
    suffix = '.fastq'
    if "--gzip" in options: suffix += '.gz'
    fastq = re.sub(".lite","",re.sub(".sra","",os.path.basename(filename)))
    if "--split-files" in options:
        fastq = (fastq+"_1"+suffix,fastq+"_2"+suffix)
    else:
        fastq += suffix
    return {'arguments': ["fastq-dump"]+options+[filename],'return_value': fastq }

@program
def fastqc(fastqfile,outdir=None,options=None):
    """Binds ``fastqc`` (`<http://www.bioinformatics.bbsrc.ac.uk/>`_) which generates a QC report of short reads present in the fastq file.
    """
    outfile = re.sub(".fastq","",os.path.basename(fastqfile))+'_fastqc.zip'
    if not(isinstance(options,list)): options = []
    if outdir and os.path.isdir(outdir):
        outfile = os.path.join(outdir,outfile)
        options += ["--outdir",outdir]
    return {'arguments': ["fastqc","--noextract"]+options+[fastqfile],'return_value': outfile}

def run_fastqc( ex, job, via='lsf' ):
    """
    Returns the name of the report file.
    """
    futures = {}
    descr = {'step':'qc','groupId':0,'type':'zip'}
    for gid,group in job.groups.iteritems():
        futures[gid] = {}
        for rid,run in group['runs'].iteritems():
            if isinstance(run,tuple):
                futures[gid][rid] = (fastqc.nonblocking(ex,run[0],via=via),
                                     fastqc.nonblocking(ex,run[1],via=via))
            else:
                futures[gid][rid] = fastqc.nonblocking(ex,run,via=via)
    for gid,group in job.groups.iteritems():
        descr['groupId'] = gid
        for rid,run in group['runs'].iteritems():
            rname = group['name']
            if len(group['runs'])>1:
                rname += "_"
                rname += group['run_names'].get(rid,str(rid))
            if isinstance(run,tuple):
                qcreport = futures[gid][rid][0].wait()
                if os.path.exists(qcreport):
                    ex.add( qcreport,
                            description=set_file_descr(rname+"_R1_fastqc.zip",**descr) )
                qcreport = futures[gid][rid][1].wait()
                if os.path.exists(qcreport):
                    ex.add( qcreport,
                            description=set_file_descr(rname+"_R2_fastqc.zip",**descr) )
            else:
                qcreport = futures[gid][rid].wait()
                if os.path.exists(qcreport):
                    ex.add( qcreport,
                            description=set_file_descr(rname+"_fastqc.zip",**descr) )
    return None


def get_fastq_files( ex, job, set_seed_length=True ):
    """
    Will replace file references by actual file paths in the 'job' object.
    These references are either 'dafl' run descriptions or urls.
    Argument 'dafl' is a dictionary of 'Daflims' objects (keys are the facility names).
    If 'set_seed_length' is true, a dictionary job.groups[gid]['seed_lengths']
    of seed lengths is constructed with values corresponding to 70% of the
    read length.
    """
    def _expand_fastq(ex,run,target):
        target2 = unique_filename_in()
        run_strip = run
        is_gz = run.endswith((".gz",".gzip"))
        is_bz2 = run.endswith((".bz",".bz2"))
        if is_gz: run_strip = re.sub('.gz[ip]*','',run)
        if is_bz2: run_strip = re.sub('.bz[2]*','',run)

        def _rewrite(input_file,output_file):
            with open(output_file,'wb',10000000) as g:
                while True:
                    chunk = input_file.read(10000000) #10Mb
                    if chunk == '': break
                    else: g.write(chunk)

        if run_strip.endswith(".tar"):
            mode = 'r'
            if is_gz: mode += '|gz'
            with open(target,'rb') as tf:
                tar = tarfile.open(fileobj=tf, mode=mode)
                tar_filename = tar.next()
                input_file = tar.extractfile(tar_filename)
                _rewrite(input_file,target2)
                tar.close()
        elif is_gz:
            input_file = gzip.open(target, 'rb')
            _rewrite(input_file,target2)
            input_file.close()
        elif is_bz2:
            input_file = bz2.BZ2File(target,mode='r')
            _rewrite(input_file,target2)
            input_file.close()
        elif run.endswith(".sra"):
            target2 = fastq_dump(ex,target,options=["--split-files"])
            if not os.path.exists(target2[1]): target2 = target2[0]
        else:
            target2 = target
        return target2
#########
    for gid,group in job.groups.iteritems():
        job.groups[gid]['seed_lengths'] = {}
        job.groups[gid]['run_names'] = {}
        for rid,run in group['runs'].iteritems():
            run_lib_name = None
            if isinstance(run,dict):
                if run.get('sequencing_library'):
                    run_lib_name = str(run['sequencing_library'])
                elif all([run.get(x) for x in ['facility','machine','run','lane']]):
                    run_lib_name = "_".join([run['machine'],str(run['run']),str(run['lane'])])
            if run.get('url'):
                run = str(run['url']).strip()
            if isinstance(run,dict) and all([x in run for x in ['facility','machine','run','lane']]):
                if not(hasattr(job,"dafl") and isinstance(job.dafl.values()[0],daflims.DAFLIMS)):
                    raise ValueError("Need DAFLIMS objects in get_fastq_files.")
                dafl1 = job.dafl[run['facility']]
                daf_data = dafl1.fetch_fastq( str(run['facility']), str(run['machine']),
                                              run['run'], run['lane'],
                                              libname=run.get('sequencing_library') )
                job.groups[gid]['runs'][rid] = daf_data['path']
                if set_seed_length:
                    job.groups[gid]['seed_lengths'][rid] = max(28,int(0.7*daf_data['cycle']))
            elif isinstance(run,str):
                run = re.search(r'^[\"\']?([^\"\';]+)[\"\']?',run).groups()[0]
                if run_lib_name is None: run_lib_name = os.path.splitext(run.split("/")[-1])[0]
                target = unique_filename_in()
                runsplit = run.split(',')
                run_pe = None
                if len(runsplit) > 1:
                    run = runsplit[0].strip()
                    run_pe = runsplit[1].strip()
                    target_pe = target+"_R2"
                if run.startswith(("http://","https://","ftp://")):
                    urllib.urlretrieve( run, target )
                    if run_pe:
                        urllib.urlretrieve( run_pe, target_pe )
                elif run.startswith("smb://"):
                    base,ext = os.path.splitext(run)
                    if ext in [".gz",".gzip"]:
                        ext = os.path.splitext(base)[1]+ext
                    if run_pe:
                        target = os.path.abspath("../%i_1%s" %(rid,ext))
                        target_pe = os.path.abspath("../%i_2%s" %(rid,ext))
                    else:
                        target = os.path.abspath("../%i%s" %(rid,ext))
                else:
                    if run.startswith("arch://"): run = os.path.join(_arch_basepath,run[7:])
                    if run_pe and run_pe.startswith("arch://"): run_pe = os.path.join(_arch_basepath,run_pe[7:])
                    if os.path.exists(run):
                        shutil.copy(run,target)
                        if run_pe: shutil.copy(run_pe, target_pe)
                    else:
                        demrun = os.path.join(demultiplex_path,run)
                        maprun = os.path.join(ex.lims.file_path,run)
                        if os.path.exists(demrun):
                            run = demrun
                            shutil.copy(run,target)
                            if run_pe:
                                run_pe = os.path.join(demultiplex_path,run_pe)
                                shutil.copy(run_pe, target_pe)
                        elif os.path.exists(maprun):
                            run = maprun
                            shutil.copy(run,target)
                            run += ".gz"
                            if run_pe: 
                                run_pe = os.path.join(ex.lims.file_path,run_pe)
                                shutil.copy(run_pe,target_pe)
                                run_pe += ".gz"
                        else:
                            raise ValueError("Could not find fastq file %s"%run)

#                run = re.sub('.seq.gz','_seq.tar',run)
                if run_pe:
                    job.groups[gid]['runs'][rid] = (_expand_fastq(ex,run,target),
                                                    _expand_fastq(ex,run_pe,target_pe))
                else:
                    job.groups[gid]['runs'][rid] = _expand_fastq(ex,run,target)
            job.groups[gid]['run_names'][rid] = re.sub(r'\s+','_',run_lib_name)
    return job

###############
# BAM/SAM files
###############
@program
def sam_to_bam(sam_filename, bam_filename=None, reheader=None):
    """Convert *sam_filename* to a BAM file. Returns the name of the created BAM file.

    Equivalent: ``samtools view -b -S [-t *reheader*] -o *bam_filename*``

    :param sam_filename: (str) the name of a SAM file.
    :param bam_filename: (str) optional name of the output BAM file.
    :param reheader: (str) if the SAM has no header, then tries to build one from either an
        assembly name, or the path to a tab-delimited file with
        `sequence_name <tab> sequence_length` on each line (samtools view ``-t`` option).
    """
    if bam_filename is None: bam_filename = unique_filename_in()
    arguments = ["samtools","view","-b","-S","-o",bam_filename]
    if reheader:
        if not os.path.exists(reheader):
            assembly = genrep.Assembly(reheader)
            reheader = unique_filename_in()
            with open(reheader,'wb') as g:
                for chr,v in assembly.chrmeta.iteritems():
                    g.write(chr+'\t'+str(v['length'])+'\n')
        arguments.extend(['-t',reheader])
    arguments.append(sam_filename)
    return {"arguments": arguments, "return_value": bam_filename}

@program
def bam_to_sam(bam_filename, no_header=False):
    """Convert *bam_filename* to a SAM file.

    Equivalent: ``samtools view [-h] bam_filename ...``
    """
    sam_filename = unique_filename_in()
    call = ['samtools','view']
    if no_header: call += '-h'
    call += ['-o',sam_filename,bam_filename]
    return {'arguments': call, 'return_value': sam_filename}

@program
def replace_bam_header(header, bamfile):
    """Replace the header of *bamfile* with that in *header*

    The header in *header* should be that of a SAM file.
    """
    return {'arguments': ['samtools','reheader',header,bamfile], 'return_value': bamfile}

@program
def sort_bam(bamfile, filename=None):
    """Sort a BAM file *bamfile* by chromosome coordinates.

    Returns the filename of the newly created, sorted BAM file.

    Equivalent: ``samtools sort ...``
    """
    if filename is None: filename = unique_filename_in()
    return {'arguments': ['samtools','sort',bamfile,filename],
            'return_value': filename + '.bam'}

@program
def sort_bam_by_read(bamfile, filename=None):
    """Sort a BAM file *bamfile* by read names.

    Returns the filename of the newly created, sorted BAM file.

    Equivalent: ``samtools sort -n ...``
    """
    if filename is None: filename = unique_filename_in()
    return {'arguments': ['samtools','sort','-n',bamfile,filename],
            'return_value': filename + '.bam'}

def read_sets(reads,keep_unmapped=False):
    """Groups the alignments in a BAM file by read.

    *reads* should be an iterator over reads, such as the object
     returned by pysam.Samfile.  The SAM/BAM file must be sorted by
     read.  ``read_sets`` removes all unmapped reads, and returns an
     iterator over lists of all AlignedRead objects consisting of the
     same read.
    """
    last_read = None
    for r in reads:
        if (not keep_unmapped) and (r.tid == -1 or r.is_unmapped):
            pass
        elif r.qname != last_read:
            if last_read != None:
                yield accum
            accum = [r]
            last_read = r.qname
        else:
            accum.append(r)
    if last_read != None:
        # We have to check, since if samfile
        # has no alignments, accum is never defined.
        yield accum

@program
def index_bam(bamfile):
    """Index a sorted BAM file.

    Returns the filename in *bamfile* with ``.bai`` appended, that is,
    the filename of the newly created index.  *bamfile* must be sorted
    for this to work.

    Equivalent: ``samtools index ...``
    """
    return {'arguments': ['samtools','index',bamfile],
            'return_value': bamfile + '.bai'}


@program
def merge_bam(files,header=None):
    """Merge a list of BAM files.

    *files* should be a list of filenames of BAM files.  They are
    merged into a single BAM file, and the filename of that new file
    is returned.
    """
    args = ['samtools','merge']
    if header: args += ["-h",header]
    if len(files) == 1:
        return {'arguments': ['echo'], 'return_value': files[0]}
    else:
        filename = unique_filename_in()
        return {'arguments': args+[filename]+files, 'return_value': filename}


@program
def external_add_nh_flag(samfile):
    outfile = unique_filename_in()
    return {'arguments': ['add_nh_flag',samfile,outfile],'return_value': outfile}


def add_nh_flag(samfile, out=None):
    """Adds NH (Number of Hits) flag to each read alignment in *samfile*.

    Scans a BAM file ordered by read name, counts the number of
    alternative alignments reported and writes them to a BAM file
    with the NH tag added.

    If *out* is ``None``, a random name is used.
    """
    if out == None:
        out = unique_filename_in()
    infile = pysam.Samfile(samfile)
    outfile = pysam.Samfile(out, "wb", template=infile)
    for readset in read_sets(infile,keep_unmapped=True):
        nh = sum((r.qlen for r in readset))/(1.0*readset[0].rlen)
        if readset[0].is_paired: nh /= 2
        nh = max(1,int(0.5+nh))
        for read in readset:
            if read.is_unmapped: nh = 0
            read.tags = read.tags+[("NH",nh)]
            outfile.write(read)
    infile.close()
    outfile.close()
    return out

def add_and_index_bam(ex, bamfile, description="", alias=None, via='local'):
    """Indexes *bamfile* and adds it to the repository.

    The index created is properly associated to *bamfile* in the
    repository, so when you use the BAM file later, the index will
    also be copied into place with the correct name.
    """
    if isinstance(description,dict): description = str(description)
    sort = sort_bam.nonblocking(ex, bamfile, via=via).wait()
    index = index_bam(ex, sort)
    ex.add(sort, description=description, alias=alias)
    description = re.sub(r'([^\[\s]+)',r'\1.bai',description,1)
    ex.add(index, description=description + " (BAM index)",
           associate_to_filename=sort, template='%s.bai')
    return sort



def poisson_threshold(mu, cutoff=0.95, max_terms=100):
    """Calculate confidence threshold for Poisson distributions.

    Returns the largest integer *k* such that, for a Poisson
    distribution random value X with mean 'mu', P(X <= k) <= 'cutoff'.
    It will calculate no farther than k = 'max_terms'.  If it reaches
    that point, it raises an exception.
    """
    if float(mu)<=1e-3: return 0
    from scipy.misc import  factorial
    from numpy      import  cumsum, exp, array
    p = cumsum( exp(-mu) * array([mu**k / float(factorial(k)) for k in range(0,max_terms)] ))
    n = len(p[p <= cutoff])
    if n == max_terms:
        raise ValueError("In poisson_threshold, reached max_terms. Try raising max_terms.")
    else:
        return n

def remove_duplicate_reads( bamfile, chromosomes,
                            maxhits=None, pilesize=1, convert=False ):
    """Filters a bam file for multi-hits above 'maxhits' and for duplicate reads beyond 'pilesize'.

    Reads with NH tag > maxhits are discarded, each genomic position
    will have at most 'pilesize' reads per library and per strand.
    If the 'convert' flag is True, the reference sequence ids are replaced by
    their names as provided in 'chromosomes'.
    """
    infile = pysam.Samfile( bamfile, "rb" )
    outname = unique_filename_in()
    header = infile.header
    pilesize = max(1,pilesize)
    if convert:
        for h in header["SQ"]:
            if h["SN"] in chromosomes:
                h["SN"] = chromosomes[h["SN"]]["name"]
    outfile = pysam.Samfile( outname, "wb", header=header )
    count_per_lib = {}
    pos_per_lib = {}
    for read in infile:
        nh = dict(read.tags).get('NH',1)
        if nh < 1:
            continue
        lpatt = re.search(r'^(.*?:.*?):',read.qname)
        if lpatt: lname = lpatt.groups()[0]
        else: lname = '1'
        lib = lname+":"+(read.is_reverse and '1' or '0')
        pos = "%s:%d" % (read.tid, read.pos)
        if pos != pos_per_lib.get(lib):
            pos_per_lib[lib] = pos
            count_per_lib[lib] = 0
        if (maxhits is None or nh <= maxhits) and count_per_lib[lib] < pilesize:
            outfile.write(read)
        count_per_lib[lib] += 1
    outfile.close()
    infile.close()
    return outname

########
# BWA
########
@program
def bwa_sw(reads_path, reference_path, sam_path, z=7, version=''):
    """Calls the BWA-SW aligner.
    `<http://bio-bwa.sourceforge.net/>`_

    :param reads_path: The path to the short reads.
    :type reads_path: str
    :param reference_path: The path to the reference to map to.
    :type reference_path: str
    :param sam_path: The place were the SAM file will be created.
    :type sam_path: str
    :param z: A balance between quality and speed. Small z is speed.
    :param version: BWA version, for instance '0.7.5a'. Currently available:
        0.5.9, 0.6.1, 0.6.2, 0.7.2, 0.7.5a
    :type z: int
    """
    if version: bwa_path = os.path.join('/software/UHTS/Aligner/bwa',str(version),'bwa')
    else: bwa_path = 'bwa'
    return {'arguments': [bwa_path, "bwasw", "-z", str(z), "-f", sam_path, reference_path, reads_path],
            'return_value': sam_path}

########
# Bowtie
########
def add_bowtie_index(execution, files, description="",
                     alias=None, index=None, bowtie2=False):
    """Add an index of a list of FASTA files to the repository.
    Returns the prefix of the bowtie index.

    :param files: (list of str) a list of file names of FASTA files. The files are
        indexed with `bowtie-build`, then a placeholder is written to the
        repository, and the six files of the bowtie index are associated
        to it. Using the placeholder in an execution will properly set up
        the whole index.
    :param description: (str) MiniLIMS description for the index files.
    :param alias: (str) an optional alias to give to the whole index so it may
        be referred to by name in future.
    :param index: (str) lets you set the actual name of the index created.
    :param bowtie2: (bool) if False, use `bowtie-build` instead of `bowtie2-build`.
    """
    if isinstance(description,dict): description = str(description)
    index = bowtie_build(execution, files, index=index, bowtie2=bowtie2)
    touch(execution, index)
    execution.add(index, description=description, alias=alias)
    execution.add(index + ".1.ebwt", associate_to_filename=index, template='%s.1.ebwt')
    execution.add(index + ".2.ebwt", associate_to_filename=index, template='%s.2.ebwt')
    execution.add(index + ".3.ebwt", associate_to_filename=index, template='%s.3.ebwt')
    execution.add(index + ".4.ebwt", associate_to_filename=index, template='%s.4.ebwt')
    execution.add(index + ".rev.1.ebwt", associate_to_filename=index, template='%s.rev.1.ebwt')
    execution.add(index + ".rev.2.ebwt", associate_to_filename=index, template='%s.rev.2.ebwt')
    return index

@program
def bowtie(index, reads, args="-Sra"):
    """Run bowtie with *args* to map *reads* against *index*.
    See `<http://bowtie-bio.sourceforge.net/index.shtml>`_.

    Returns the filename of bowtie's output file.  *args* gives the
    command line arguments to bowtie, and may be either a string or a
    list of strings.
    """
    index = re.sub(r'([/_])bowtie2/',r'\1bowtie/',index)
    sam_filename = unique_filename_in()
    if isinstance(args, (tuple,list)):
        options = list(args)
    elif isinstance(args, basestring):
        options = args.split(" ")
    else:
        raise ValueError("bowtie's args keyword argument requires a string or a "+\
                         "list of strings.  Received: "+str(args))
    if isinstance(reads, list):
        reads = ",".join(reads)
    if isinstance(reads, tuple):
        if isinstance(reads[0],list):
            reads1 = ",".join(reads[0])
        if isinstance(reads[1],list):
            reads2 = ",".join(reads[1])
        else:
            reads1 = reads[0]
            reads2 = reads[1]
        reads = "-1 "+reads1+" -2 "+reads2
        if not("-X" in options): options += ["-X","800"]
    return {"arguments": ["bowtie"]+options+[index, reads, sam_filename],
            "return_value": sam_filename}

@program
def bowtie2(index, reads, args=''):
    """Run `bowtie2` with *args* to map *reads* against *index*.
    Returns the name of bowtie's output file.
    See `<http://bowtie-bio.sourceforge.net/bowtie2/index.shtml>`_.

    :param index: (str) path to the bowtie2 index.
    :param reads: (list or tuple) if unpaired, a list of paths to each of the fastq files;
        if paired, a tuple `(path_to_R1, path_to_R2)`.
    :param args: (str or list) command line arguments to bowtie - either a string ("-k 20 ...")
        or a list of strings (["-k","20",...]).
    """
    index = re.sub(r'([/_])bowtie/',r'\1bowtie2/',index)
    sam_filename = unique_filename_in()
    options = ["-x",index,"-S",sam_filename]
    if isinstance(args, (tuple,list)):
        options += list(args)
    elif isinstance(args, basestring):
        options += args.split()
    else:
        raise ValueError("bowtie2's args keyword argument requires a string or a "+\
                         "list of strings.  Received: "+str(args))
    if isinstance(reads, list):
        options += ["-U",",".join(reads)]
    elif isinstance(reads, basestring):
        options += ["-U",reads]
    elif isinstance(reads, tuple):
        if isinstance(reads[0],list):
            reads1 = ",".join(reads[0])
        if isinstance(reads[1],list):
            reads2 = ",".join(reads[1])
        else:
            reads1 = reads[0]
            reads2 = reads[1]
        options += ["-1", reads1, "-2", reads2]
        if not("-X" in options): options += ["-X","800"]
    return {"arguments": ["bowtie2"]+options, "return_value": sam_filename}

@program
def bowtie_build(files, index=None, bowtie2=False):
    """Create a bowtie index from *files*.
    Return the prefix of the resulting bowtie index.

    :param files: (str or list) name of a FASTA file, or a list
        giving the names of several FASTA files.
    :param bowtie2: (bool) if False, use `bowtie-build` instead of `bowtie2-build`.
    """
    if bowtie2: main_call = "bowtie2-build"
    else:       main_call = "bowtie-build"
    if index == None:
        index = unique_filename_in()
    if isinstance(files,list):
        files = ",".join(files)
    return {'arguments': [main_call, '-f', files, index], 'return_value': index}


def parallel_bowtie( ex, index, reads, unmapped=None, n_lines=16000000, bowtie_args=[],
                     add_nh_flags=False, bowtie_2=False, via='local' ):
    """Run bowtie in parallel on pieces of *reads*.

    Splits *reads* into chunks *n_lines* long, then runs `bowtie` with
    arguments *bowtie_args* to map each chunk against *index*.
    The results are converted to BAM and merged.
    The name of the single, merged BAM file is returned.

    Bowtie does not set the NH flag on its SAM file output.  If the
    *add_nh_flags* argument is ``True``, this function calculates
    and adds the flag before merging the BAM files.

    The *via* argument determines how the jobs will be run.  The
    default, ``'local'``, runs them on the same machine in separate
    threads.  ``'lsf'`` submits them via LSF.
    """
    un_cmd = "--un"
    if isinstance(reads,tuple):
        sf1 = sorted(split_file(ex, reads[0], n_lines = n_lines))
        sf2 = sorted(split_file(ex, reads[1], n_lines = n_lines))
        subfiles = [(f,sf2[n]) for n,f in enumerate(sf1)]
        mlim = 12
        if bowtie_2: un_cmd = "--un-conc"
    else:
        subfiles = split_file(ex, reads, n_lines=n_lines)
        mlim = 6
    if bowtie_2: btcall = bowtie2.nonblocking
    else:        btcall = bowtie.nonblocking
    if unmapped:
        futures = [btcall(ex, index, sf,
                          args=bowtie_args+[un_cmd,unmapped+"_"+str(n),"-p","5"],
                          via=via, memory=mlim, threads=5)
                   for n,sf in enumerate(subfiles)]
    else:
        futures = [btcall(ex, index, sf, args=bowtie_args+["-p","5"],
                          via=via, memory=mlim, threads=5) for sf in subfiles]
    samfiles = [f.wait() for f in futures]
    futures = []
    if add_nh_flags:
        futures = [external_add_nh_flag.nonblocking(ex, sf, via=via) for sf in samfiles]
    else:
        futures = [sam_to_bam.nonblocking(ex, sf, via=via) for sf in samfiles]
    if unmapped:
        if isinstance(reads,tuple):
            if bowtie_2:
                cat([unmapped+"_"+str(n)+".1" for n in range(len(subfiles))],unmapped+"_1")
                cat([unmapped+"_"+str(n)+".2" for n in range(len(subfiles))],unmapped+"_2")
            else:
                cat([unmapped+"_"+str(n)+"_1" for n in range(len(subfiles))],unmapped+"_1")
                cat([unmapped+"_"+str(n)+"_2" for n in range(len(subfiles))],unmapped+"_2")
        else:
            cat([unmapped+"_"+str(n) for n in range(len(subfiles))],unmapped)
    bamfiles = [sort_bam.nonblocking(ex, f.wait(), via=via) for f in futures]
    return merge_bam.nonblocking(ex, [f.wait() for f in bamfiles], via=via).wait()

################################################################################
# Postprocessing #
################################################################################
@program
def bamstats(bamfile):
    """Wrapper to the ``bamstat`` program.

    This program computes read mapping statistics on a bam file. The output will
    be parsed and converted to a dictionary.
    """
    def extract_pairs(s,head,foot):
        m=re.search(head+r'\n([\d\s]*)\n'+foot,s,
                    flags=re.MULTILINE).groups()[0].splitlines()
        def f(x):
            (a,b) = re.search(r'(\d+)\s(\d+)',x).groups()
            return (int(a),int(b))
        return dict([f(x) for x in m])
    def coverage_stats(p):
        results = {}
        try:
            infile = pysam.Samfile(bamfile, "rb")
            results = {'cmd_line': "|".join(infile.header['PG'][0].values())}
            infile.close()
        except:
            pass
        s=''.join(p.stdout)
        if not(re.search(r'Total (\d+)',s)):
               time.sleep(60)
               s=''.join(p.stdout)
        results["read_length"]=int(re.search(r'Read length (\d+)',s).groups()[0])
        results["genome_size"]=int(re.search(r'Genome size (\d+)',s).groups()[0])
        results["nb_positions"]=int(re.search(r'Nb positions (\d+)',s).groups()[0])
        results["multi_hits"]=extract_pairs(s,"Hits Reads","Total")
        results["total"]=int(re.search(r'Total (\d+)',s).groups()[0])
        [total,fwd,rev]=re.search(r'Alignments (\d+)\s*\(fwd:\s+(\d+)/rev:\s+(\d+)\)',
                                  s,flags=re.MULTILINE).groups()
        results["alignments"]={"total": int(total),
                                "fwd": int(fwd),
                                "rev": int(rev)}
        results["unmapped"]=int(re.search(r'Unmapped ([\d.]+)',s).groups()[0])
        results["expected_coverage"]=float(re.search(r'Expected coverage ([\d.]+)',
                                                     s).groups()[0])
        results["actual_coverage"]=float(re.search(r'Actual coverage ([\d.]+)',
                                                   s).groups()[0])
        results["mismatches"]=extract_pairs(s,"Mismatches Reads","")
        return results
    return {"arguments": ["bamstat",bamfile], "return_value": coverage_stats}

@program
def plot_coverage(bamfile,pdffile,title):
    """Creates a read coverage histogram of the data in pdf form.
    """
    if pdffile is None: pdffile = unique_filename_in()
    return {'arguments': ["bamQC.sh",bamfile,pdffile,"'"+title+"'"],
            'return_value': pdffile}

@program
def plot_stats(sample_stats,script_path=""):
    """Wrapper to the ``pdfstats.R`` script which generates
    a pdf report of the mapping statistics.

    The input is the dictionary return by the ``bamstats`` call.
    This is passed as a json file to the R script.
    Returns the pdf file created by the script.
    """
    stats_file = unique_filename_in()
    with open( stats_file, 'w' ) as f:
        json.dump(sample_stats,f)
        f.write("\n")
    pdf_file = unique_filename_in()
    return {'arguments': ["R","--vanilla","--slave","-f",
                          os.path.join(script_path,"pdfstats.R"),
                          "--args"] + [stats_file,pdf_file],
            'return_value': pdf_file}

def add_pdf_stats( ex, processed, group_names, script_path,
                   description="mapping_report.pdf", via='local' ):
    """Runs the 'plot_stats' function and adds its pdf output to the execution's repository.

    Arguments are the output of 'map_groups' ('processed'),
    a dictionary of group_id to names used in the display,
    the path to the script used by 'plot_stats',
    and the 'description' to use in the repository.

    Returns the name of the pdf file.
    """
    all_stats = {}
    futures = {}
    for gid in group_names.keys():
        for i,mapped in enumerate(processed[gid].values()):
            name = group_names[gid] or str(gid)
            if 'libname' in mapped:
                name = mapped['libname']
            if name in all_stats:
                name += ":"+str(i+1)
            if 'fullstats' in mapped:
                all_stats[name+":full"] = mapped['fullstats']
                all_stats[name+":filter"] = mapped['stats']
            else:
                all_stats[name] = mapped['stats']
            _pdf = unique_filename_in()
            bam = mapped['bam']
            futures[(gid,name)] = plot_coverage.nonblocking(ex,bam,_pdf,name,via=via,memory=8)
    pdf = plot_stats(ex, all_stats, script_path=script_path)
    ex.add(pdf,description)
    for grid,fut in futures.iteritems():
        try:
            _pdf = fut.wait()
            if os.path.exists(_pdf):
                _desc = re.sub(r'.*\.pdf',grid[1]+"_coverage_plot.pdf",description)
                ex.add(_pdf,description=_desc)
        except:
            pass
    return pdf

def pprint_bamstats(sample_stats, textfile=None):
    """Pretty stdout-print for sample_stats.

    :param sample_stats: The input is the dictionary returned by the ``bamstats`` call.
    :type sample_stats: dict
    :param textfile: If defined, output is printed as textfile instead.
    :type textfile: string
    """
    if textfile:
        with open(textfile, 'w') as f:
            for k, v in sample_stats.iteritems():
                f.writelines(str(k) + "\t" + str(v) + "\n")
    else:
        width_left = max([len(x) for x in sample_stats.keys()]) + 5
        width_right = max([len(str(x)) for x in sample_stats.values()]) + 5
        width_table = width_left + width_right + 7
        print "-" * width_table
        for k, v in sample_stats.iteritems():
            print "* {0:{lwh}} | {1:>{rwh}} *".format(k,v, lwh=width_left,rwh=width_right)
        print "-" * width_table

############################################################

def map_reads( ex, fastq_file, chromosomes, bowtie_index,
               bowtie_2=False, maxhits=5, antibody_enrichment=50,
               keep_unmapped=True, remove_pcr_duplicates=True, bwt_args=None,
               via='lsf' ):
    """Runs ``bowtie`` in parallel over lsf for the `fastq_file` input.
    Returns the full bamfile, its filtered version (see 'remove_duplicate_reads')
    and the mapping statistics dictionary (see 'bamstats').

    The input file will be split into subfiles if it contains more than 10M lines.
    The 'add_nh_flag' function will be called to add the number of hits per read
    in the bowtie output.
    If 'remove_pcr_duplicates' is *True*, the 'chromosomes' and 'maxhits' arguments
    are passed to the 'remove_duplicate_reads'
    function and the 'antibody_enrichment' will be used as input to
    the 'poisson_threshold' function to compute its 'pilesize' argument.

    The mapping statistics dictionary is pickled and added to the execution's
    repository, as well as both the full and filtered bam files.
    """
    if bwt_args is None: bwt_args = []
    maxhits = int(maxhits)
    antibody_enrichment = int(antibody_enrichment)
    if bowtie_2:
        bwtarg = ["-k", str(max(20,maxhits))]+bwt_args
        if not ("--local" in bwtarg or "--end-to-end" in bwtarg):
            bwtarg += ["--end-to-end"] #"--local"
        if not any(opt in bwtarg for opt in ["-D","-R","-N","-i"]):
# Specific custom options from user by config file
            preset = ["--very-fast","--fast","--sensitive","--very-sensitive"]
            #preset += [p+'-local' for p in preset]
# Uncomment if --local becomes the defaut mode some day
            if not any(p in bwtarg for p in preset):
# No specific options or preset set by user: default preset
                if "--local" in bwtarg: bwtarg += ["--sensitive-local"]
                else:                   bwtarg += ["--sensitive"]
# Presets have constraints on the seed length: use the preset's value
            if "-L" in bwtarg:
                seedlen_idx = bwtarg.index("-L")
                bwtarg = bwtarg[:seedlen_idx]+bwtarg[seedlen_idx+2:]
        btcall = bowtie2.nonblocking
    else:
        bwtarg = ["-Sam", str(max(20,maxhits))]+bwt_args
        if not("--best" in bwtarg):     bwtarg += ["--best"]
        if not("--strata" in bwtarg):   bwtarg += ["--strata"]
        if not("--chunkmbs" in bwtarg): bwtarg += ["--chunkmbs","512"]
        unmapped = unique_filename_in()
        btcall = bowtie.nonblocking
    is_paired_end = isinstance(fastq_file,tuple)
    un_cmd = "--un"
    if is_paired_end:
        linecnt = count_lines( ex, fastq_file[0] )
        mlim = 8
        if bowtie_2: un_cmd = "--un-conc"
    else:
        linecnt = count_lines( ex, fastq_file )
        mlim = 4
    if keep_unmapped:
        unmapped = unique_filename_in()
    else:
        unmapped = None
    if linecnt>10000000:
        n_lines = 4*(linecnt/40+1)#has to be a multiple of 4
        sorted_bam = parallel_bowtie( ex, bowtie_index, fastq_file, unmapped=unmapped,
                                      n_lines=n_lines, bowtie_args=bwtarg,
                                      add_nh_flags=True, bowtie_2=bowtie_2, via=via )
    else:
        bwtarg += [un_cmd, unmapped]
        future = btcall( ex, bowtie_index, fastq_file, bwtarg+["-p","5"], via=via, memory=mlim, threads=5 )
        samfile = future.wait()
        bam = add_nh_flag( samfile )
        sorted_bam = sort_bam.nonblocking(ex, bam, via=via).wait()
    sorted_bai = index_bam(ex, sorted_bam)
###    sorted_bam = add_and_index_bam( ex, bam, set_file_descr(name+"complete.bam",**bam_descr) )
    full_stats = bamstats( ex, sorted_bam )
    return_dict = {"fullbam": sorted_bam}
    if unmapped:
        if is_paired_end and os.path.exists(unmapped+"_1"):
            touch( ex, unmapped )
            gzipfile( ex, unmapped+"_1" )
            gzipfile( ex, unmapped+"_2" )
            return_dict['unmapped'] = unmapped
        elif os.path.exists(unmapped):
            gzipfile( ex, unmapped )
            return_dict['unmapped'] = unmapped
    if remove_pcr_duplicates:
        thresh = poisson_threshold( antibody_enrichment*full_stats["actual_coverage"] )
        reduced_bam = remove_duplicate_reads( sorted_bam, chromosomes, maxhits, thresh, convert=True )
        return_dict['poisson_threshold'] = thresh
#        reduced_bam = sort_bam.nonblocking(ex, bam2, via=via).wait()
        index2 = index_bam(ex, reduced_bam)
#        reduced_bam = add_and_index_bam( ex, bam2, set_file_descr(name+"filtered.bam",**bam_descr) )
        filtered_stats = bamstats( ex, reduced_bam )
        return_dict['bam'] = reduced_bam
        return_dict['fullstats'] = full_stats
        return_dict['stats'] = filtered_stats
    else:
        infile = pysam.Samfile( sorted_bam, "rb" )
        reduced_bam = unique_filename_in()
        header = infile.header
        for h in header["SQ"]:
            if h["SN"] in chromosomes:
                h["SN"] = chromosomes[h["SN"]]["name"]
        outfile = pysam.Samfile( reduced_bam, "wb", header=header )
        for read in infile:
            nh = dict(read.tags).get('NH',1)
            if nh < 1:
                continue
            if nh <= maxhits:
                outfile.write(read)
        outfile.close()
        infile.close()
#        reduced_bam = sort_bam.nonblocking(ex, bam2, via=via).wait()
        index2 = index_bam(ex, reduced_bam)
#        reduced_bam = add_and_index_bam( ex, bam2, set_file_descr(name+"filtered.bam",**bam_descr) )
        return_dict['bam'] = reduced_bam
        return_dict['stats'] = full_stats
    return return_dict

############################################################

def map_groups( ex, job_or_dict, assembly, map_args=None,
                bowtie2=False, logfile=sys.stdout, debugfile=sys.stderr ):
    """Fetches fastq files and bowtie indexes, and runs the 'map_reads' function for
    a collection of samples described in a 'Frontend' 'job'.

    Arguments are:

    :param ex: a 'bein' execution environment to run jobs in,
    :param job_or_dict: a 'frontend.Job' object, or a dictionary with keys 'groups',
    :param assembly: a 'genrep.Assembly' object.
    :param map_args: a dictionary of arguments passed to map_reads.
    :param bowtie2: if False, `bowtie` will be used instead of `bowtie2`. The paths to both
        indexes are expected to differ only by the name of the last containing directory, namely
        `bowtie` or `bowtie2` respectively.

    Returns a dictionary with keys *group_id* from the job object and values dictionaries
    mapping *run_id* to the corresponding return value of the 'map_reads' function.

    """
    processed = {}
    file_names = {}
    options = {}
    chromosomes = {}
    if map_args is None:
        map_args = {}
    map_args.setdefault('bwt_args',[])
    if isinstance(map_args['bwt_args'],basestring):
        map_args['bwt_args'] = str(map_args['bwt_args']).split()
    if isinstance(job_or_dict, frontend.Job):
        options = job_or_dict.options
        groups = job_or_dict.groups
    elif isinstance(job_or_dict,dict) and 'groups' in job_or_dict:
        if 'options' in job_or_dict:
            options = job_or_dict['options']
        groups = job_or_dict['groups']
    else:
        raise TypeError("job_or_dict must be a frontend.Job object or a dictionary with keys 'groups'.")
    pcr_dupl = options.get('discard_pcr_duplicates',True)
    if isinstance(pcr_dupl,basestring):
        pcr_dupl = pcr_dupl.lower() in ['1','true','t']
    chromosomes = dict((v['ac'],{'name':k,'length':v['length']}) for k,v in assembly.chrmeta.iteritems())
    if assembly.intype == 2: # transcriptome is more redundant
        map_args['maxhits'] = max(int(map_args.get('maxhits') or 50),50)
    index_path = assembly.index_path
    for gid,group in groups.iteritems():
        processed[gid] = {}
        file_names[gid] = {}
        if 'name' in group:
            group_name = re.sub(r'\s+','_',group['name'])
        else:
            group_name = str(gid)
        if not 'runs' in group:
            group = {'runs': group}
        for rid,run in group['runs'].iteritems():
            if (not bowtie2) and 'seed_lengths' in group and group['seed_lengths'].get(rid) > 0:
                seed_len = str(group['seed_lengths'][rid])
                if "-l" in map_args['bwt_args']:
                    map_args['bwt_args'][map_args['bwt_args'].index("-l")+1] = seed_len
                else:
                    map_args['bwt_args'] += ["-l",seed_len]
            name = group_name
            if len(group['runs'])>1:
                name += "_"
                name += group['run_names'].get(rid,str(rid))
            m = map_reads( ex, run, chromosomes, index_path, bowtie_2=bowtie2,
                           remove_pcr_duplicates=pcr_dupl, **map_args )
            bam_descr = {'type': 'bam', 'ucsc': '1'}
            py_descr = {'type':'py','view':'admin','comment':'pickle file'}
            fq_descr = {'type': 'fastq'}
            fqn_descr = {'type': 'none','view':'admin'}
            bam_descr.update({'step':'bowtie', 'groupId':gid})
            py_descr.update({'step':'bowtie', 'groupId':gid})
            fq_descr.update({'step':'bowtie', 'groupId':gid})
            fqn_descr.update({'step':'bowtie', 'groupId':gid})
            if 'fullstats' in m:
                add_pickle( ex, m['fullstats'], set_file_descr(name+"_full_bamstat",**py_descr) )
            if 'stats' in m:
                add_pickle( ex, m['stats'], set_file_descr(name+"_filter_bamstat",**py_descr) )
            if 'unmapped' in m:
                if isinstance(run,tuple):
                    ex.add( m['unmapped'], description=set_file_descr(name+"_unmapped.fastq.gz",**fqn_descr) )
                    ex.add( m['unmapped']+"_1.gz", description=set_file_descr(name+"_unmapped_1.fastq.gz",**fq_descr),
                            associate_to_filename=m['unmapped'], template='%s_1.fastq.gz' )
                    ex.add( m['unmapped']+"_2.gz", description=set_file_descr(name+"_unmapped_2.fastq.gz",**fq_descr),
                            associate_to_filename=m['unmapped'], template='%s_2.fastq.gz' )
                else:
                    ex.add( m['unmapped']+".gz", set_file_descr(name+"_unmapped.fastq.gz",**fq_descr) )
            if 'poisson_threshold' in m:
                add_pickle( ex, m['poisson_threshold'], set_file_descr(name+"_Poisson_threshold",**py_descr) )
            if 'bam' in m:
                bdescr = set_file_descr(name+"_filtered.bam",**bam_descr)
                ex.add(m['bam'], description=bdescr)
                bdescr = re.sub(r'([^\[\s]+)',r'\1.bai',bdescr,1)
                ex.add(m['bam']+".bai", description=bdescr+" (BAM index)", associate_to_filename=m['bam'], template='%s.bai')
            file_names[gid][rid] = str(name)
            m.update({'libname': str(name)})
            processed[gid][rid] = m
    add_pickle( ex, file_names, set_file_descr('file_names',step='stats',type='py',view='admin',comment='pickle file') )
    return processed

@program
def bam_to_density( bamfile, output, chromosome_accession=None, chromosome_name=None,
                    nreads=-1, merge=-1, read_extension=-1, se=False, convert=True, sql=False,
                    args=None ):
    """
    :param bamfile: input BAM file
    :param output: basename of output file
    :param chromosome_accession: globally unique chromosome identifier
    :param chromosome_name: specific chromosome in species context
    :param nreads: If 0: normalise by total tag count*1e-7, if >0: uses 1e-7*nreads as factor, by default: no normalization
    :param merge: only if -p is not specified, specify it with this value
    :param read_extension: bam2wig argument 'Tags (pseudo-)size'
    :param se: Consider paired ends as single ends when generating the density
    :param convert: whether or not to convert chromosome labels
    :param sql: whether or not to create an SQL database
    :param args: bam2wig arguments given directly by the user

    Runs the ``bam2wig`` program on a bam file and
    normalizes for the total number of reads
    provided as argument 'nreads'.

    Returns the name of the output wig or sql file(s) (if 'sql' is True).

    Use 'convert'=False if the bam already uses chromosome names instead of ids.
    """
    b2w_args = ["-w", str(nreads), "-s", bamfile, "-o", output]
    if isinstance(args,(list,tuple)):
        b2w_args += list(args)
    if convert and chromosome_accession is not None and chromosome_name is not None:
        b2w_args += ["-a",chromosome_accession,"-n",chromosome_name]
    elif chromosome_name is not None:
        b2w_args += ["-a",chromosome_name]
    elif chromosome_accession is not None:
        b2w_args += ["-a",chromosome_accession]
    if merge>=0 and not('-p' in b2w_args):
        b2w_args += ["-p",str(merge)]
        if se and not('--single_end' in b2w_args):
            b2w_args += ["--single_end"]
    if read_extension>0 and not('-q' in b2w_args):
        b2w_args += ["-q",str(read_extension)]
    if sql:
        b2w_args += ["-d"]
        if merge<0:
            files = [output+"fwd.sql",output+"rev.sql"]
        else:
            files = [output+"merged.sql"]
    else:
        if merge<0:
            b2w_args += ["-6"]
        files = output
    return {"arguments": ["bam2wig"]+b2w_args, "return_value": files}

def parallel_density_wig( ex, bamfile, chromosomes,
                          nreads=1, merge=-1, read_extension=-1,
                          se=False, convert=True,
                          description="", alias=None,
                          b2w_args=None, via='lsf' ):
    """Runs 'bam_to_density' in parallel
    for every chromosome in the 'chromosomes' list with 'sql' set to False.
    Returns a single text wig file.
    """
    mlim = max(int(nreads*1.5e-7),6)
    futures = [bam_to_density.nonblocking( ex, bamfile, unique_filename_in(),
                                           v.get('ac'), k,
                                           nreads, merge, read_extension, se, convert,
                                           False, args=b2w_args, via=via, memory=mlim )
               for k,v in chromosomes.iteritems()]
    results = []
    for f in futures:
        try:
            results.append(f.wait())
        except ProgramFailed:
            pass
    output = cat(results)
    ex.add( output, description=description, alias=alias )
    return output

def parallel_density_sql( ex, bamfile, chromosomes,
                          nreads=1, merge=-1, read_extension=-1,
                          se=False, convert=True,
                          b2w_args=None, via='lsf' ):
    """Runs 'bam_to_density' for every chromosome in the 'chromosomes' list.

    Generates 1 or 2 files depending
    if 'merge'>=0 (shift and merge strands into one track)
    or 'merge'<0 (keep seperate tracks for each strand) and returns their basename.
    """
    futures = {}
    mlim = max(int(nreads*1.5e-7),6)
    for k,v in chromosomes.iteritems():
        futures[k] = bam_to_density.nonblocking( ex, bamfile, unique_filename_in(),
                                                 v.get('ac'), k,
                                                 nreads, merge, read_extension, se, convert,
                                                 False, args=b2w_args, via=via, memory=mlim )
    output = unique_filename_in()
    touch(ex,output)
    trackargs = {'fields': ['start','end','score'],
                 'chrmeta': chromosomes,
                 'info': {'datatype':'quantitative',
                          'nreads': nreads,
                          'read_extension': read_extension}}
    if merge < 0:
        trev = track.track(output+"rev.sql",**trackargs)
        tfwd = track.track(output+"fwd.sql",**trackargs)
        for k in chromosomes.keys():
            wig = str(futures[k].wait())
            if not(os.path.exists(wig)): touch(ex,wig)
            twig = track.track(wig,format='bed')
            trev.write(twig.read(selection={'strand':'-'}))
            tfwd.write(twig.read(selection={'strand':'+'}))
        trev.close()
        tfwd.close()
    else:
        trackargs['info']['shift'] = merge
        if se: trackargs['info']['single_end'] = "True"
        tboth = track.track(output+"merged.sql",**trackargs)
        for k in chromosomes.keys():
            wig = str(futures[k].wait())
            if not(os.path.exists(wig)): touch(ex,wig)
            twig = track.track(wig,format='bedgraph')
            tboth.write(twig.read())
        tboth.close()
    return output

############################################################

def densities_groups( ex, job_or_dict, file_dict, chromosomes, via='lsf' ):
    """
    Arguments are:

    * ``'ex'``: a 'bein' execution environment to run jobs in,

    * ``'job_or_dict'``: a 'Frontend' 'job' object, or a dictionary with keys 'groups',

    * ``'file_dict'``: a dictionary of files,

    * ``'chromosomes'``: a dictionary with keys 'chromosome_id' as used in the bowtie indexes and values a dictionary with usual chromosome names and their lengths,

    Returns a dictionary with keys *group_id* from the job object and values the files fo each group ('bam' and 'wig').
    """
    processed = {}
    options = {}
    if isinstance(job_or_dict,frontend.Job):
        options = job_or_dict.options
        groups = job_or_dict.groups
    elif isinstance(job_or_dict,dict) and 'groups' in job_or_dict:
        if 'options' in job_or_dict:
            options = job_or_dict['options']
        groups = job_or_dict['groups']
    else:
        raise TypeError("job_or_dict must be a frontend.Job object or a dictionary with keys 'groups'.")
    merge_strands = int(options.get('merge_strands',-1))
    suffixes = ["fwd","rev"]
    if merge_strands >= 0: suffixes = ["merged"]
    ucsc_bigwig = options.get('ucsc_bigwig',False)
    b2w_args = options.get('b2w_args',[])
    se = options.get('as_single_end','0').lower() in ['1','true','t']
    processed = {}
    for gid,group in groups.iteritems():
        if 'name' in group:
            group_name = re.sub(r'\s+','_',group['name'])
        else:
            group_name = gid
        mapped = file_dict[gid]
        if not isinstance(mapped,dict):
            raise TypeError("processed values must be dictionaries with keys *run_ids* or 'bam'.")
        if 'bam' in mapped:
            mapped = {'_': mapped}
        for k in mapped.keys():
            if not 'libname' in mapped[k]:
                mapped[k]['libname'] = group_name+"_"+str(k)
            if not 'stats' in mapped[k]:
                mapped[k]['stats'] = bamstats( ex, mapped[k]["bam"] )
            if int(options.get('read_extension',-1)) < 1:
                options['read_extension'] = mapped[k]['stats']['read_length']
        wig = []
        pars0 = {'groupId':gid, 'step':'density', 'type':'none', 'view':'admin'}
        pars1 = {'groupId':gid, 'step':'density', 'type':'sql'}
        for m in mapped.values():
            output = parallel_density_sql( ex, m["bam"], chromosomes,
                                           nreads=m["stats"]["total"],
                                           merge=merge_strands,
                                           read_extension=options['read_extension'],
                                           se=se, convert=False,
                                           b2w_args=b2w_args, via=via )
            wig.append(output)
            ex.add( output, description=set_file_descr(m['libname']+'.sql',**pars0) )
            [ex.add( output+s+'.sql', description=set_file_descr(m['libname']+'_'+s+'.sql',**pars1),
                     associate_to_filename=output, template='%s_'+s+'.sql' )
             for s in suffixes]
        if len(mapped)>1:
            merged_bam = merge_bam(ex, [m['bam'] for m in mapped.values()])
#            ids = [m['libname'] for m in mapped.values()]
            merged_wig = dict((s, merge_sql(ex, [x+s+".sql" for x in wig], via=via))
                              for s in suffixes)
            [ex.add( merged_wig[s], description=set_file_descr(group_name+"_"+s+".sql",**pars1) ) for s in suffixes]
        else:
            merged_bam = mapped.values()[0]['bam']
            merged_wig =  dict((s, wig[0]+s+".sql") for s in suffixes)
        processed[gid] = {'bam': merged_bam, 'wig': merged_wig,
                          'read_length': mapped.values()[0]['stats']['read_length']}
        if ucsc_bigwig:
            out = unique_filename_in()
            for s in suffixes:
                track.convert(merged_wig[s],(out+s,"bigWig"))
                ex.add(out+s,
                       description=set_file_descr(group_name+"_"+s+".bw",groupId=gid,step='density',type='bigWig',ucsc='1'))
    processed.update({'read_extension': options.get('read_extension',-1),
                      'genome_size': mapped.values()[0]['stats']['genome_size']})
    return processed

def mapseq_workflow(ex, job, assembly, map_args, gl, bowtie2=False, via="local",
                    logfile=sys.stdout, debugfile=sys.stderr):
    logfile.write("Map reads.\n");logfile.flush()
    map_args.setdefault("via",via)
    mapped_files = map_groups( ex, job, assembly, map_args, bowtie2, logfile, debugfile )
    logfile.write("Make stats:\n");logfile.flush()
    logfile.write("GroupId_GroupName:\t")
    for k,v in job.groups.iteritems():
        logfile.write(str(k)+"_"+str(v['name'])+"\t");debugfile.flush()
        pdf = add_pdf_stats( ex, mapped_files, {k:v['name']},
                             gl.get('script_path',''),
                             description=set_file_descr(v['name']+"_mapping_report.pdf",
                                                        groupId=k,step='stats',type='pdf'),
                             via=via )
    if job.options['compute_densities']:
        chrmeta = {}
        if isinstance(assembly,genrep.Assembly): chrmeta = assembly.chrmeta
        elif isinstance(assembly,dict):          chrmeta = assembly.get('chrmeta',{})
        logfile.write("\ncomputing densities.\n");logfile.flush()
        if int(job.options.get('read_extension',-1))<=0:
            job.options['read_extension'] = mapped_files.values()[0].values()[0]['stats']['read_length']
        density_files = densities_groups( ex, job, mapped_files, chrmeta, via=via )
        logfile.write("Finished computing densities.\n");logfile.flush()
    else:
        density_files = None
    return 0


def get_bam_wig_files( ex, job, minilims=None, hts_url=None, suffix=['fwd','rev'],
                       script_path='', fetch_unmapped=False, via='lsf' ):
    """
    Will replace file references by actual file paths in the 'job' object.
    These references are either 'mapseq' keys or urls.
    """
    read_exts = {}
    mapped_files = {}
    for gid,group in job.groups.iteritems():
        mapped_files[gid] = {}
        if 'name' in group:
            group_name = re.sub(r'\s+','_',group['name'])
        else:
            group_name = str(gid)
        job.groups[gid]['name'] = group_name
        for rid,run in group['runs'].iteritems():
            try:
                file_loc = re.search(r'^[\"\']?([^\"\';]+)[\"\']?',str(run['url']).strip()).groups()[0]
            except AttributeError:
                raise AttributeError("BAM files not found.")
            bamfile = unique_filename_in()
            wig = {}
            name = group_name
            stats = {}
            p_thresh = None
            fastqfiles = None
            if len(group['runs'])>1:
                if run.get('sequencing_library'):
                    name += "_"+str(run['sequencing_library'])
                elif all([run.get(x) for x in ['machine','run','lane']]):
                    name += "_".join(['',run['machine'],str(run['run']),str(run['lane'])])
                else:
                    name += "_"+os.path.splitext(file_loc.split("/")[-1])[0]
            if file_loc.startswith(("http://","https://","ftp://")):
                urllib.urlretrieve( file_loc, bamfile )
                if not(file_loc.startswith('ftp://')) \
                        and urllib.urlopen(file_loc+".bai").getcode() == 200:
                    urllib.urlretrieve( file_loc+".bai", bamfile+".bai" )
                else:
                    index_bam(ex, bamfile)
                    if "the alignment is not sorted" in ''.join(ex.programs[-1].stderr):
                        bamfile = sort_bam.nonblocking(ex, bamfile, via=via).wait()
                        index_bam(ex, bamfile)
            elif file_loc.startswith("arch://") or os.path.exists(file_loc):
                if file_loc.startswith("arch://"): file_loc = os.path.join(_arch_basepath,file_loc[7:])
                assert os.access(file_loc, os.R_OK), "No read access to %s" % file_loc
                shutil.copy( file_loc, bamfile )
                if os.path.exists(file_loc+".bai"):
                    shutil.copy( file_loc+".bai", bamfile+".bai" )
                else:
                    index_bam(ex, bamfile)
                    if "the alignment is not sorted" in ''.join(ex.programs[-1].stderr):
                        bamfile = sort_bam.nonblocking(ex, bamfile, via=via).wait()
                        index_bam(ex, bamfile)
            elif os.path.exists(minilims) and os.path.exists(os.path.join(minilims+".files",file_loc)):
                assert os.access(os.path.join(minilims+".files",file_loc), os.R_OK), "No read access to %s" % file_loc
                MMS = MiniLIMS(minilims)
                file_loc = os.path.join(minilims+".files",file_loc)
                shutil.copy( file_loc, bamfile )
                shutil.copy( file_loc+".bai", bamfile+".bai" )
                exid = max(MMS.search_executions(with_text=run['key']))
                allfiles = {}
                for fid in MMS.search_files(source=('execution',exid)):
                    tf = MMS.fetch_file(fid)
                    descr = re.sub(r'^[^\[]+:','',tf['description'],count=1)
                    filename = re.search(r'^([^\s\[]+)',descr).groups()[0]
                    allfiles[filename] = fid
                    if str(run['url']) == str(tf['repository_name']):
                        name = re.search(r'^(.*)_[^_]*.bam',descr).groups()[0]
                stats_id = allfiles.get(name+"_filter_bamstat") or allfiles.get(name+"_full_bamstat")
                with open(MMS.path_to_file(stats_id)) as q:
                    stats = pickle.load(q)
                p_thresh = -1
                if fetch_unmapped:
                    fastqname = unique_filename_in()
                    if name+"_unmapped_1.fastq.gz" in allfiles:
                        fastq_loc = [MMS.path_to_file(allfiles[name+"_unmapped_1.fastq.gz"]),
                                     MMS.path_to_file(allfiles[name+"_unmapped_2.fastq.gz"])]
                        fastqfiles = (fastqname+"_R1",fastqname+"_R2")
                    elif name+"_unmapped.fastq.gz" in allfiles:
                        fastq_loc = [MMS.path_to_file(allfiles[name+"_unmapped.fastq.gz"])]
                        fastqfiles = (fastqname,)
                    else:
                        fastq_loc = []
                        fastqfiles = ()
                    for i,fqf in enumerate(fastq_loc):
                        with open(fastqfiles[i],'wb',10000000) as f:
                            temp = gzip.open(fqf, 'rb')
                            while True:
                                chunk = temp.read(10000000) #10Mb
                                if chunk == '': break
                                else: f.write(chunk)
                            temp.close()
                    if len(fastqfiles) == 1:
                        fastqfiles = fastqfiles[0]
                if name+"_Poisson_threshold" in allfiles:
                    pickle_thresh = allfiles[name+"_Poisson_threshold"]
                    with open(MMS.path_to_file(pickle_thresh)) as q:
                        p_thresh = pickle.load(q)
                if 'gdv_json' in allfiles:
                    with open(MMS.path_to_file(allfiles['gdv_json'])) as q:
                        job.options['gdv_project'] = pickle.load(q)
                if hts_url is not None:
                    htss = frontend.Frontend( url=hts_url )
                    ms_job = htss.job( run['key'] )
                    if int(ms_job.options.get('read_extension',-1))>0 and int(ms_job.options.get('read_extension'))<110:
                        read_exts[rid] = int(ms_job.options['read_extension'])
                    else:
                        read_exts[rid] = stats.get('read_length',50)
                else:
                    ms_job = job
                msintp = int(ms_job.options.get('input_type_id',0) or 0)
                if msintp > 0: job.assembly.intype = msintp
                if str(ms_job.options.get('compute_densities','False')).lower() in ['1','true','t']:
                    job.options['merge_strands'] = int(ms_job.options.get('merge_strands',-1))
                    if ((job.options['merge_strands']<0 and len(suffix)>1) or
                        (job.options['merge_strands']>-1 and len(suffix)==1)):
                        wigfile = unique_filename_in()
                        wig_ids = dict(((allfiles[name+'_'+s+'.sql'],s),
                                        wigfile+'_'+s+'.sql') for s in suffix)
                        [MMS.export_file(x[0],s) for x,s in wig_ids.iteritems()]
                        wig = dict((x[1],s) for x,s in wig_ids.iteritems())
            else:
                raise ValueError("Couldn't find this bam file anywhere: %s" %file_loc)
            mapped_files[gid][rid] = {'bam': bamfile,
                                   'stats': stats or bamstats( ex, bamfile ),
                                   'poisson_threshold': p_thresh,
                                   'libname': name,
                                   'wig': wig}
            if fetch_unmapped: mapped_files[gid][rid].update({'unmapped_fastq':fastqfiles})
    if len(read_exts)>0 and not('read_extension' in job.options):
        c = dict((x,0) for x in read_exts.values())
        for x in read_exts.values():
            c[x]+=1
        job.options['read_extension'] = [k for k,v in c.iteritems() if v==max(c.values())][0]
    for gid, group in job.groups.iteritems():
        for rid,run in group['runs'].iteritems():
            if ('read_extension' in job.options) and (read_exts.get(rid) != job.options['read_extension']):
                mapped_files[gid][rid]['wig'] = []
            if not(isinstance(mapped_files[gid][rid]['stats'],dict)):
                stats = mapped_files[gid][rid]['stats'].wait()
                mapped_files[gid][rid]['stats'] = stats
                grname = mapped_files[gid][rid]['libname']
                pdf = add_pdf_stats( ex, {gid:{rid:{'stats':stats}}},
                                     {gid: grname},
                                     script_path,
                                     set_file_descr(grname+"_mapping_report.pdf",step='import_data',type='pdf',groupId=gid) )
                mapped_files[gid][rid]['poisson_threshold'] = poisson_threshold( 50*stats["actual_coverage"] )
            mapped_files[gid][rid].update(job.files.get(gid,{}).get(rid,{}))
    job.files = mapped_files
    return job

#-----------------------------------#
# This code was written by the BBCF #
# http://bbcf.epfl.ch/              #
# webmaster.bbcf@epfl.ch            #
#-----------------------------------#
