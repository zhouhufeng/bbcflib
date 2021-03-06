Using scripts and configuration files
=====================================

Each of our pipelines can be run on the command-line using the scripts provided in our `repository <https://github.com/bbcf/bbcfutils/tree/master/Python>`_. Theses scripts use configuration files to set the various pipeline options.

Here is a typical workflow that uses both ``mapseq`` and ``chipseq``. The configuration file will contain the following sections: first a ``Global variables`` section that defines the local environment for the pipelines::

    [Global variables]
    genrep_url='http://bbcf-serv01.epfl.ch/genrep/'
    bwt_root='/db/genrep'
    fastq_root='/scratch/cluster/daily/htsstation/mapseq/'
    script_path='/archive/epfl/bbcf/share'
    [[hts_chipseq]]
    url='http://htsstation.epfl.ch/chipseq/'
    download='http://htsstation.epfl.ch/lims/chipseq/chipseq_minilims.files/'
    [[hts_mapseq]]
    url='http://htsstation.epfl.ch/mapseq/'
    download='http://htsstation.epfl.ch/lims/mapseq/mapseq_minilims.files/'
    [[gdv]]
    url='http://gdv.epfl.ch/pygdv'
    email='your.email@yourplace.org'
    key='pErS0na1&keY%0Ng2V'

For example, if you intend to download data from the LIMS, you need to setup your account::

    [[lims]]
    user='limslogin'
    [[[passwd]]]
    lgtf='xxxxxxxx'
    gva='yyyyyyy'

Similarly, if you want to receive an email upon completion of the pipeline, submit the relevant informations for the sender email::

    [[email]]
    sender='webmaster@lab.edu'
    smtp='local.machine.edu'

Then comes the job description::

    [Job]
    description='config test'
    assembly_id='mm9'
    email='toto@place.no'
    [Options]
    read_extension=65
    input_type=0
    compute_densities=True
    discard_pcr_duplicates=True

Experimental conditions correspond to `groups` which are numbered, each condition may have any number of replicates (called `runs`) which are associated with their respective group via its numeric `group_id`::

    [Groups]
    [[1]]
    control=True
    name='unstimulated'
    [[2]]
    control=False
    name='stimulated'

    [Runs]
    [[1]]
    url='http://some.place.edu/my_control.fastq'
    group_id=1
    [[2]]
    url='http://some.place.edu/my_test1.fastq'
    group_id=2
    [[3]]
    url='http://some.place.edu/my_test2.fastq'
    group_id=2

Such a configuration file can be passed as command-line argument to the scripts `run_mapseq.py <https://github.com/bbcf/bbcfutils/blob/master/Python/run_mapseq.py>`_ and `run_chipseq.py <https://github.com/bbcf/bbcfutils/blob/master/Python/run_chipseq.py>`_, e.g.::

    python run_mapseq.py -c my_config.txt -d test_lims

We next analyse how these python scripts are using these configuration and processing the files. First we import all the relevant modules::

    from bbcflib import daflims, genrep, frontend, gdv, common
    from bbcflib.mapseq import *
    from bbcflib.chipseq import *

Then connect to a ``MiniLIMS`` and parse the configuration file::

    M = MiniLIMS( 'test_lims' )
    (job,gl) = frontend.parseConfig( 'my_config.txt' )

This returns two dictionaries, one with the job description and one with the global variables sections. Then we fetch an assembly and define a few options::

    g_rep = genrep.GenRep( url=gl["genrep_url"], root=gl["bwt_root"], intype=job.options.get('input_type') )
    assembly = g_rep.assembly( job.assembly_id )
    dafl = dict((loc,daflims.DAFLIMS( username=gl['lims']['user'], password=pwd )) for loc,pwd in gl['lims']['passwd'].iteritems())
    job.options['ucsc_bigwig'] = job.options.get('ucsc_bigwig') or True
    job.options['gdv_project'] = job.options.get('gdv_project') or False
    via = 'lsf'

then start an execution environment in which we

* fetch the fastq files using :func:`bbcflib.mapseq.get_fastq_files`
* launch the bowtie mapping via :func:`bbcflib.mapseq.map_groups`
* generate a pdf report of the mapping statistics with :func:`bbcflib.mapseq.add_pdf_stats`
* if requested, make a density profile using :func:`bbcflib.mapseq.densities_groups`
* create the corresponding project and tracks in :doc:`GDV <bbcflib_gdv>`.

This corresponds to the code below::

    with execution( M, description='test_mapseq' ) as ex:
        job = get_fastq_files( job, ex.working_directory, dafl )
        mapped_files = map_groups( ex, job, ex.working_directory, assembly, {'via': via} )
        pdf = add_pdf_stats( ex, mapped_files,
                             dict((k,v['name']) for k,v in job.groups.iteritems()),
                             gl['script_path'] )
        if job.options['compute_densities']:
            if not(job.options.get('read_extension')>0):
                job.options['read_extension'] = mapped_files.values()[0].values()[0]['stats']['read_length']
            density_files = densities_groups( ex, job, mapped_files, assembly.chromosomes, via=via )
            if job.options['gdv_project']:
                gdv_project = gdv.create_gdv_project( gl['gdv']['key'], gl['gdv']['email'],
                                                      job.description, hts_key,
                                                      assembly.nr_assembly_id,
                                                      gdv_url=gl['gdv']['url'], public=True )
                add_pickle( ex, gdv_project, description='py:gdv_json' )

Finally all the output files are returned as a dictionary::

    allfiles = common.get_files( ex.id, M )

this dictionary will be organized by file type and provide a descriptive name and the actual (repository) file name, e.g.::

    {'none': {'7XgDex9cTCn8JjEk005Q': 'test.sql'},
    'py': {'hkwjU7nnhE0uuZostJmF': 'file_names', 'M844kgtaGpgybnq5APsb': 'test_full_bamstat', 'cRzKabyKnN0dcRHaAVsj': 'test_Poisson_threshold', 'j4EWGj2riic7Xz47hKhj': 'test_filter_bamstat'},
    'sql': {'7XgDex9cTCn8JjEk005Q_merged.sql': 'test_merged.sql'},
    'bigwig': {'UjaseL2p8Z1RnDetZ2YX': 'test_merged.bw'},
    'pdf': {'13wUAjrQEikA5hXEgTt': 'mapping_report.pdf'},
    'bam': {'mJP4dqP1f2K6Pw2iZ2LZ': 'test_filtered.bam', 'IRn3o49zIZ2JOOkMxAJl.bai': 'test_complete.bam.bai', 'IRn3o49zIZ2JOOkMxAJl': 'test_complete.bam', 'mJP4dqP1f2K6Pw2iZ2LZ.bai': 'test_filtered.bam.bai'}}

If you then want to continue with a ChIP-seq analysis, you can start a new execution, collect the files with :func:`bbcflib.mapseq.get_bam_wig_files` and run :func:`bbcflib.chipseq.workflow_groups` with the updated job::

    with execution( M, description='test_chipseq' ) as ex:
        job = get_bam_wig_files( ex, job, 'test_lims', gl['hts_mapseq']['url'], gl['script_path'], via=via )
        chipseq_files = workflow_groups( ex, job, assembly.chromosomes, gl['script_path'] )


Parameters common to all modules
''''''''''''''''''''''''''''''''

The following sections will be needed in all modules::

    [Global variables]
    genrep_url='http://bbcf-serv01.epfl.ch/genrep/'
    script_path='/archive/epfl/bbcf/share'

    [Job]
    description='config test'
    assembly_id='mm9'


In addition, a set of numbered `groups` (experimental conditions) and for each of them a set of replicates (`runs`)::

    [Groups]
    [[1]]
    control=True
    name='unstimulated'
    [[2]]
    name='stimulated'

    [Runs]
    [[1]]
    url='http://some.place.edu/my_control.fastq'
    group_id=1
    [[2]]
    url='http://some.place.edu/my_test1.fastq'
    group_id=2
    [[3]]
    url='http://some.place.edu/my_test2.fastq'
    group_id=2

For all modules but the Mapping one, mapping results and their parameters (as gotten from :func:`bbcflib.mapseq.get_bam_wig_files`) can be overwritten (which is very useful for testing purposes)::

    [Files]
    [[1]]
    bam='my_control.bam'
    unmapped_fastq='unmapped_control.fastq'
    wig='somefile.wig'
    libname='new_run_name'
    poisson_threshold=None
    group_id=1
    [[[stats]]]
    read_length=100     # etc.
    [[2]]
    bam='my_test1.bam'
    group_id=2
    [[3]]
    bam='my_test2.bam'
    group_id=2

Mapping parameters
''''''''''''''''''

In the mapping module, the following options are valid, with the following defaults::

    [Options]
    bowtie2=True# if False will use bowtie1
    input_type=0# type of mapping: 0=genome, 1=exonome, 2=transcriptome
    compute_densities=True# run bam2wig after bowtie
    ucsc_bigwig=False# create bigwig to upload to UCSC genome browser
    create_gdv_project=False# create a new project on GDV and upload tracks at the end
    discard_pcr_duplicates=True# apply PCR artifact filter
    merge_strand=-1# shift value for merging the two strand-specific densities, -1 means no merging
    read_extension=-1# value of the read extension, the -q parameter of bam2wig (-1 means read length)
    map_args={"maxhits":5, "antibody_enrichment":50,
               "keep_unmapped":True, "bwt_args":None}# a dictionary of arguments passed to map_reads
    b2w_args=[]# list of options to the bam2wig program

See :py:func:`bbcflib.mapseq.map_reads` for the arguments that can be passed via `map_args`, for example, to use custom bowtie options, the number of hits allowed for each read and the expected enrichement ratio::

    map_args={"maxhits":1,"antibody_enrichment":100,"bwt_args":["-5","10","-n","1"]}

To use "local" mapping mode with bowtie2::

    map_args={"bwt_args":["--local"]}

ChIP-seq parameters
'''''''''''''''''''

In the ChIP-seq module, the following options are valid, with the following defaults::

    [Options]
    ucsc_bigwig=False
    create_gdv_project=False
    merge_strand=-1
    read_extension=-1
    b2w_args=[]
    peak_deconvolution=False# run the deconvolution algorithm
    run_meme=False# run Meme motif search on peaks
    macs_args=["--bw","200"]# list of MACS command-line arguments

RNA-seq parameters
'''''''''''''''''''

In the RNA-seq module, the following options are valid, with the following defaults::

    [Options]
    unmapped=True         # remap on transcriptome the reads that did not map to the genome initially
    find_junctions=False  # use SOAPsplice to find splicing junctions

SNP parameters
'''''''''''''''''''

In the RNA-seq module, the following options are valid, with the following defaults::

    [Options]
    minsnp=5
    mincov=40
