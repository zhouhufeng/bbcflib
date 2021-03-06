"""
======================
Module: bbcflib.common
======================

Utility functions common to several pipelines.
"""

# Built-in modules #
import os, sys, time, string, random, re, json, functools

#-------------------------------------------------------------------------#

iupac = {'M':'AC', 'Y':'CT', 'R':'AG', 'S':'CG', 'W': 'AT', 'K':'GT',
         'B':'CGT', 'D':'AGT', 'H':'ACT', 'V':'ACG',
         'N': 'ACGT'}

translate = {"TTT": "F", "TTC": "F", "TTA": "L", "TTG": "L/START",
             "CTT": "L", "CTC": "L", "CTA": "L", "CTG": "L",
             "ATT": "I", "ATC": "I", "ATA": "I", "ATG": "M & START",
             "GTT": "V", "GTA": "V", "GTC": "V", "GTG": "V/START",
             "TCT": "S", "TCC": "S", "TCA": "S", "TCG": "S",
             "CCT": "P", "CCC": "P", "CCA": "P", "CCG": "P",
             "ACT": "T", "ACC": "T", "ACA": "T", "ACG": "T",
             "GCT": "A", "GCC": "A", "GCA": "A", "GCG": "A",
             "TAT": "Y", "TAC": "Y", "TAA": "STOP", "TAG": "STOP",
             "CAT": "H", "CAC": "H", "CAA": "Q", "CAG": "Q",
             "AAT": "N", "AAC": "N", "AAA": "K", "AAG": "K",
             "GAT": "D", "GAC": "D", "GAA": "E", "GAG": "E",
             "TGT": "C", "TGC": "C", "TGA": "STOP", "TGG": "W",
             "CGT": "R", "CGC": "R", "CGA": "R", "CGG": "R",
             "AGT": "S", "AGC": "S", "AGA": "R", "AGG": "R",
             "GGT": "G", "GGC": "G", "GGA": "G", "GGG": "G" }

def revcomp(seq):
    cmpl = dict((('A','T'),('C','G'),('T','A'),('G','C'),
                 ('a','t'),('c','g'),('t','a'),('g','c'),
                 ('M','K'),('K','M'),('Y','R'),('R','Y'),('S','S'),('W','W'),
                 ('m','k'),('k','m'),('y','r'),('r','y'),('s','s'),('w','w'),
                 ('B','V'),('D','H'),('H','D'),('V','B'),
                 ('b','v'),('d','h'),('h','d'),('v','b'),
                 ('N','N'),('n','n')))
    return "".join(reversed([cmpl.get(x,x) for x in seq]))

#-------------------------------------------------------------------------#
def unique_filename_in(path=None):
    """Return a random filename unique in the given path.

    The filename returned is twenty alphanumeric characters which are
    not already serving as a filename in *path*.  If *path* is
    omitted, it defaults to the current working directory.
    """
    if path == None: path = os.getcwd()
    def random_string():
        return "".join([random.choice(string.letters + string.digits) for x in range(20)])
    while True:
        filename = random_string()
        files = [f for f in os.listdir(path) if f.startswith(filename)]
        if files == []: break
    return filename

#-------------------------------------------------------------------------#
def pause():
    """Pause until the user hits Return."""
    print "Pause... Hit any key to continue."
    sys.stdin.readline()
    return None

#-------------------------------------------------------------------------#
def program_exists(program):
    """Check if *program* exists in local $PATH."""
    for path in os.environ["PATH"].split(os.pathsep):
        exe = os.path.join(path, program)
        if os.path.isfile(exe) and os.access(exe, os.X_OK):
            return True
    return False

#-------------------------------------------------------------------------#
def set_file_descr(filename,**kwargs):
    """Implements file naming compatible with the 'get_files' function::

        >>> set_file_descr("toto",**{'tag':'pdf','step':1,'type':'doc','comment':'ahaha'})
        'pdf:toto[step:1,type:doc] (ahaha)'

    If 'tag' and/or comment are ommitted::

        >>> set_file_descr("toto",step=1,type='doc')
        'toto[step:1,type:doc]'

    :param filename: (str) name to be given to the file in the web interface.
    :rtype: str

    Possible keys to *kwargs*:

    * 'tag': (str) added in front of the file name: 'tag:filename[others]'. Usually the file extension.
    * 'group': (str) sample name.
    * 'step': (str or int) step in the analysis.
    * 'type': (str) type of file, file extension ('doc','txt','bam',...).
    * 'view': (1 or 0) whether it is visible in the web interface for non-administrator user. [1]
    * 'ucsc': (1 or 0) whether to link with the "View in UCSC" URL in the web interface. [0]
    * 'gdv': (1 or 0) whether to link with the "View in GDV" URL in the web interface. [0]
    * 'comment': (str) whatever. Added in parentheses after all the rest.
    """
    file_descr = filename
    argskeys = kwargs.keys()
    if 'tag' in kwargs:
        file_descr = kwargs['tag']+":"+filename
        argskeys.remove('tag')
    comment = ''
    if 'comment' in argskeys:
        comment = " ("+str(kwargs['comment'])+")"
        argskeys.remove('comment')
    plst = (",").join([str(k)+":"+str(kwargs[k]) for k in argskeys])
    file_descr += "["+plst+"]"
    file_descr += comment
    return file_descr

#-------------------------------------------------------------------------#
def normalize_url(url):
    """Produce a fixed form for an HTTP URL.

    Make sure the URL begins with http:// and does *not* end with a /.

    >>> normalize_url('http://bbcf.epfl.ch')
    'http://bbcf.epfl.ch'
    >>> normalize_url('http://bbcf.epfl.ch/')
    'http://bbcf.epfl.ch'
    >>> normalize_url('bbcf.epfl.ch/')
    'http://bbcf.epfl.ch'
    """
    # url = url.lower()
    if not(url.startswith(("http://","https://","ftp://"))):
        url = "http://" + url
    return url.strip("/")

#-------------------------------------------------------------------------#
def cat(files,out=None,skip=0):
    """Concatenates files.

    :param files: (list of str) list of file names of the files to concatenate.
    :param out: (str) name of the output file. By default it is a 20-chars random string.
        If this output file is not empty, *files* are appended to it.
    :param skip: (int) number of lines to skip at the beginning of *each* file (common header). [0]
    """
    if len(files) > 1:
        out = out or unique_filename_in()
        if os.path.exists(out): mode = "a"
        else: mode = "w"
        with open(out,mode) as f1:
            for inf in files:
                with open(inf,"r") as f2:
                    for i in range(skip):
                        f2.readline()
                    [f1.write(l) for l in f2]
    elif len(files) == 1:
        out = files[0]
    return out

#-------------------------------------------------------------------------#
def track_header( descr, ftype, url, ffile ):
    header = "track type="+ftype+" name="+re.sub(r'\[.*','',descr)
    url += ffile
    header += " bigDataUrl="+url+" "
    style = " visibility=4 "
    if ftype=="bigWig":
        style = " visibility=2 windowingFunction=maximum"
        if re.search(r'_rev.bw ',descr): style+= " color=0,10,200"
        if re.search(r'_fwd.bw ',descr): style+= " color=200,10,0"
    return header+style+"\n"

#"track type="+type+" name='"+fname+"' bigDataUrl="+htsurl+style+"\n"

#-------------------------------------------------------------------------#
def timer(function):
    """ A decorator that makes the decorated *function* return its execution time. """
    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        t1 = time.time()
        result = function(*args, **kwargs)
        t2 = time.time()
        print "  Execution time of function '%s': %.3f s." % (function.__name__, t2-t1)
        return result
    return wrapper

#-------------------------------------------------------------------------#

def isnum(s):
    """Return True if string *s* represents a number, False otherwise"""
    try:
        float(s)
        return True
    except ValueError:
        return False

#-------------------------------------------------------------------------#

def unique(seq, fun=None):
    """
    Return all unique elements in *seq*, preserving order - unlike list(set(seq)),
    and almost as fast. Permits this sort of filter: unique(seq, lambda x: x.lower())
    """
    if fun is None:
        def fun(x): return x
    seen = {}
    result = []
    for item in seq:
        marker = fun(item)
        if marker in seen: continue
        seen[marker] = 1
        result.append(item)
    return result


##############################
#-------- PROGRAMS --------###
##############################


try:
    from bein import program

    @program
    def gzipfile(files,args=None):
        """Runs gzip on files."""
        if not(isinstance(files,list)):
            files=[files]
        gzcall = ['gzip']
        if args:
            gzcall += args
        gzcall += files
        return {"arguments": gzcall, "return_value": None}

        #-------------------------------------------------------------------------#
    @program
    def gunzipfile(files,args=None):
        """Runs gzip on files."""
        if not(isinstance(files,list)):
            files=[files]
        gzcall = ['gunzip']
        if args:
            gzcall += args
        gzcall += files
        unzipped = [f[:-3] for f in files if f.endswith('.gz')]
        return {"arguments": gzcall, "return_value": unzipped}

        #-------------------------------------------------------------------------#
    @program
    def join_pdf(files):
        """Uses 'ghostscript' to join several pdf files into one.
        """
        out = unique_filename_in()
        gs_args = ['gs','-dBATCH','-dNOPAUSE','-q','-sDEVICE=pdfwrite',
                   '-sOutputFile=%s'%out]
        gs_args += files
        return {"arguments": gs_args, "return_value": out}

        #-------------------------------------------------------------------------#
    @program
    def coverageBed(file1,file2):
        """Binds ``coverageBed`` from the 'BedTools' suite.
        """
        return {"arguments": ['coverageBed','-a',file1,'-b',file2], "return_value": None}

        #-------------------------------------------------------------------------#
    @program
    def intersectBed(file1,file2):
        """Binds ``intersectBed`` from the 'BedTools' suite.
        """
        return {"arguments": ['intersectBed','-a',file1,'-b',file2], "return_value": None}

        #-------------------------------------------------------------------------#
    @program
    def track_convert( fileIn, fileOut=None, formatIn=None, formatOut=None,
                       assembly=None, chrmeta=None ):
        if fileOut is None: fileOut = unique_filename_in()
        args = [fileIn,fileOut]
        if formatIn:  args += ["--format1",str(formatIn)]
        if formatOut: args += ["--format2",str(formatOut)]
        if assembly:  args += ["--assembly",str(assembly)]
        if chrmeta:   args += ["--chrmeta",json.dumps(chrmeta)]
        return {"arguments": ["track_convert"]+args, "return_value": fileOut}
        #-------------------------------------------------------------------------#
    @program
    def gfminer_run( job ):
        gminer_args = ["--"+str(k)+"="+str(v) for k,v in job.iteritems()]
        def _split_output(p):
            files = ''.join(p.stdout).strip().split(',')
            return files
        return {"arguments": ["gfminer_run"]+gminer_args,
                "return_value": _split_output}

        #-------------------------------------------------------------------------#
    def merge_sql( ex, sqls, outdir=None, datatype='quantitative', via='lsf' ):
        """Run ``gfminer``'s 'merge_scores' function on a set of sql files
        """
        if outdir == None:
            outdir = unique_filename_in()
        if not(os.path.exists(outdir)):
            os.mkdir(outdir)
        if len(sqls) == 1:
            return sqls[0]
        gfminer_job = {"operation": "merge_scores", "output": outdir,
                       "datatype": datatype,
                       "args": "'"+json.dumps({"trackList":",".join(sqls)})+"'"}
        files = gfminer_run.nonblocking(ex,gfminer_job,via=via).wait()
        return files[0]

        #-------------------------------------------------------------------------#
    def intersect_many_bed(ex,files,via='lsf'):
        """Runs ``intersectBed`` iteratively over a list of bed files.
        """
        out = files[0]
        for f in files[1:]:
            next = unique_filename_in()+".bed"
            intersectBed.nonblocking( ex, out, f, via=via, stdout=next ).wait()
            out = next
        return out

        #-------------------------------------------------------------------------#
    @program
    def sam_faidx(fasta,locus=[]):
        """
        Locus a list of regions to extract, such as::

            ["2738_NC_000073.5:10456789-10458795",
             "2738_NC_000073.5:12456789-12458795"]
        """
        def _parse_fasta(p):
            retval = []
            seq = ''
            for x in p.stdout:
                if x.startswith('>'):
                    if seq:
                        retval.append(seq.upper())
                        seq = ''
                    continue
                seq += x.strip(' \t\r\n')
            if seq: retval.append(seq.upper())
            return retval

        return {"arguments": ["samtools","faidx",str(fasta)]+locus,
                "return_value": _parse_fasta}

    @program
    def fasta_length(file):
        """Binds the `fastalength` program and returns a `chromosomes` dictionary::

            {'chr1': {'name': 'chr1', 'length': xxxx}, ...}

        """
        def _len_to_dict(p):
            chroms = {}
            for l in p.stdout:
                row = l.strip().split()
                if len(row) < 2: continue;
                chroms[row[1]] = {'name': row[1], 'length': int(row[0])}
            return chroms
        return {'arguments': ['fastalength', file], 'return_value': _len_to_dict}

    @program
    def fasta_composition(file, frequency=False):
        """Binds the `fastacomposition` program and returns a dictionary with keys the nucleotides ('A', 'C', 'G', 'T') and values the counts or frequencies in the file.
        """
        def _parse_line(p):
            fastacomp = {}
            for l in p.stdout:
                row = l.strip().split()
                fastacomp = dict((row[n].upper(),int(row[n+1]))
                                 for n in range(1,len(row),2))
                break
            if frequency:
                tot = 1.0*sum(fastacomp.values())
                fastacomp = dict((k,x/tot) for k,x in fastacomp.iteritems())
            return fastacomp
        return {'arguments': ['fastacomposition', file], 'return_value': _parse_line}

#-------------------------------------------------------------------------#
    def get_files( id_or_key, minilims, by_type=True, select_param=None ):
        """Retrieves a dictionary of files created by an htsstation job identified by its key
        or bein id in a MiniLIMS.

        The dictionary keys are the file types (e.g. 'pdf', 'bam', 'py' for python objects),
        the values are dictionaries with keys repository file names and values actual file
        descriptions (names to provide in the user interface).

        'select_param' can be used to select a subset of files: if it is a string or a list of strings,
        then only files containing these parameters will be returned,
        and if it is a dictionary, only files with parameters matching the key/value pairs will be returned.
        """
        if isinstance(select_param,str): select_param = [select_param]
        if isinstance(id_or_key, str):
            try:
                exid = (minilims.search_executions(with_text=id_or_key,fails=True)\
                       +minilims.search_executions(with_text=id_or_key,fails=False))[0]
            except ValueError, v:
                raise ValueError("No execution with key "+id_or_key)
        else:
            exid = id_or_key
        file_dict = {}
        allf = dict((y['repository_name'],y['description']) for y in
                    [minilims.fetch_file(x) for x in minilims.search_files(source=('execution',exid))])
        for f,d in allf.iteritems():
            tag_d = d.split(':')
            tag = None
            if len(tag_d)>1 and not(re.search("\[",tag_d[0])):
                tag = tag_d[0]
                d = ":".join(tag_d[1:])
            pars_patt = re.search(r'\[(.*)\]',d)
            if not(pars_patt):
                pars = "group:0,step:0,type:none,view:admin"
                re.sub(r'([^\s\[]*)',r'\1['+pars+']',d,1)
            else:
                pars = pars_patt.groups()[0]
            par_dict = dict(x.split(":") for x in pars.split(","))
            if select_param:
                if isinstance(select_param,dict):
                    if not(all([k in par_dict and par_dict[k]==v for k,v in select_param.iteritems()])):
                        continue
                else:
                    if not(all([k in par_dict for k in select_param])):
                        continue
            cat = (by_type and par_dict.get('type')) or tag or 'none'
            if cat in file_dict:
                file_dict[cat][f]=d
            else:
                file_dict[cat] = {f: d}
        return file_dict

        #-------------------------------------------------------------------------#
except ImportError: print "Warning: no module named 'bein'. @program imports skipped."

#-----------------------------------#
# This code was written by the BBCF #
# http://bbcf.epfl.ch/              #
# webmaster.bbcf@epfl.ch            #
#-----------------------------------#
