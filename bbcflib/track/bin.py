from bbcflib.track import *
from bbcflib.common import program_exists
import subprocess, tempfile, os


class BinTrack(Track):
    """
    Generic Track class for binary files.
    """
    def __init__(self,path,**kwargs):
        Track.__init__(self,path,**kwargs)
        self.format = kwargs.get("format",'bin')
        self.fields = kwargs.get("fields",['chr','start','end'])

    def _run_tool(self, tool_name, args):
        if not program_exists(tool_name):
            raise OSError("Program not found in $PATH: %s" % tool_name)
        proc = subprocess.Popen([tool_name]+args, stderr=subprocess.PIPE)
        stdout, stderr = proc.communicate()
        if stderr: raise OSError("%s exited with message: %s" % (tool_name,stderr))

    def _make_selection(self, selection):
        reg = [None,None,None]
        if isinstance(selection, dict):
            if 'chr' in selection:
                reg[0] = selection['chr']
            if 'start' in selection:
                if isinstance(selection['start'],tuple):
                    reg[1:] = [str(selection['start'][0]),
                               str(selection['start'][1])]
                elif 'end' in selection and not(isinstance(selection['end'],tuple)):
                    reg[1:] = [str(selection['start']),
                               str(selection['end'])]
            elif 'end' in selection and isinstance(selection['end'],tuple):
                reg[1:] = [str(selection['end'][0]),
                           str(selection['end'][1])]
        elif isinstance(selection, basestring):
            reg[0] = selection
        return reg


############################# BigWig via UCSC tools ##############################

class BigWigTrack(BinTrack):
    """
    BinTrack class for BigWig files (extension ".bigWig", ".bigwig" or ".bw").

    Fields are::

        ['chr','start','end','score']

    will use *bedGraphToBigWig* (write) and *bigWigToBedGraph* (read) and use
    the BedGraphTrack class.
    """
    def __init__(self,path,**kwargs):
        kwargs['format'] = 'bigWig'
        kwargs['fields'] = ['chr','start','end','score']
        BinTrack.__init__(self,path,**kwargs)
        self.bedgraph = None
        self.chrfile = None

    def open(self):
        if self.bedgraph is None:
            tmp = tempfile.NamedTemporaryFile(dir='./')
            self.bedgraph = os.path.abspath(tmp.name)
            tmp.close()

    def close(self):
        if self.chrfile and self.bedgraph:
            try:
                self._run_tool('bedGraphToBigWig', [self.bedgraph, self.chrfile, self.path])
            except OSError as ose:
                os.remove(self.chrfile)
                os.remove(self.bedgraph)
                raise OSError(ose)
        if self.chrfile is not None:
            os.remove(self.chrfile)
            self.chrfile = None
        if self.bedgraph is not None:
            if os.path.exists(self.bedgraph):
                os.remove(self.bedgraph)
            self.bedgraph = None

    def read(self, selection=None, fields=None, **kw):
        """
        :param selection: list of dict of the type
            `[{'chr':'chr1','start':(12,24)},{'chr':'chr3','end':(25,45)},...]`,
            where tuples represent ranges.
        :param fields: (list of str) list of field names.
        """
        self.open()
        if not(fields): fields = self.fields
        fields = [f for f in self.fields if f in fields]
        reg = self._make_selection(selection)
        options = []
        if reg[0]: options += ["-chrom="+reg[0]]
        if reg[1]: options += ["-start="+reg[1]]
        if reg[2]: options += ["-end="+reg[2]]
        self._run_tool('bigWigToBedGraph', options+[self.path, self.bedgraph])
        t = track(self.bedgraph,format='bedGraph',chrmeta=self.chrmeta,info=self.info)
        return t.read(selection=selection,fields=fields,**kw)

    def write(self, source, **kw):
        if self.chrfile is None:
            self.chrfile = tempfile.NamedTemporaryFile(dir='./',delete=False)
            for c,v in self.chrmeta.iteritems():
                self.chrfile.write("%s %i\n"%(c,v['length']))
            self.chrfile.close()
            self.chrfile = os.path.abspath(self.chrfile.name)
        self.open()
        kw['mode'] = 'append'
        try:
            with track(self.bedgraph,format='bedgraph',chrmeta=self.chrmeta) as f:
                f.write(source,**kw)
        except:
            os.remove(self.chrfile)
            os.remove(self.bedgraph)
            raise

################################ Bam via pysam ################################

try:
    import pysam
    class BamTrack(BinTrack):
        """
        BinTrack class for Bam files (extension ".bam").

        Fields are::

            ['chr','start','end','score','name','strand','flag','seq','qual','cigar','tags','paired','positions']

        'score': mapping quality (MAPQ).
        'name': read ID.
        'qual': Phred-scaled read quality (ASCII+33, same as in fastq).
        'cigar': CIGAR string (match / mismatch / indel etc.).
        'tags': dictionary of tags, e.g. {'NH':12, ...}.
        'paired': 0 if unpaired, 1 if first read of a pair, 2 if second.
        'positions': list of positions the read mapped to.

        Uses *pysam* to read the binary bam file and extract the relevant fields.
        Write is not implemented in this class.
        """
        def __init__(self,path,**kwargs):
            kwargs['format'] = 'bam'
            kwargs['fields'] = ['chr','start','end','score','name','strand',
                                'flag','seq','qual','cigar','tags','paired']
            BinTrack.__init__(self,path,**kwargs)
            self.filehandle = None
            self.open()
            for h in self.filehandle.header["SQ"]:
                self.chrmeta[h["SN"]] = {'length':h["LN"]}
            self.close()

        def open(self):
            try:
                self.filehandle = pysam.Samfile(self.path, "rb")
                if not(os.path.exists(self.path+".bai")):
                    self._run_tool('samtools', ["index",self.path])
            except ValueError:
                self.filehandle = pysam.Samfile(self.path, "r")
                #header = {'SQ':[{'SN':chr,'LN':v['length']} for chr,v in self.chrmeta.iteritems()]}
                #self.filehandle = pysam.Samfile(self.path, "r", header=header)

        def close(self):
            self.filehandle.close()

        def read(self, selection=None, fields=None, **kw):
            """
            :param selection: list of dict of the type
                `[{'chr':'chr1','start':(12,24)},{'chr':'chr3','end':(25,45)},...]`,
                where tuples represent ranges.
            :param fields: (list of str) list of field names.
            """
            self.open()
            if not(isinstance(selection,(list,tuple))): selection = [selection]
            if fields is None: fields = self.fields
            else: fields = [f for f in fields if f in self.fields]
            srcl = [self.fields.index(f) for f in fields]

            def _bamrecord(stream, srcl):
                for sel in selection:
                    reg = self._make_selection(sel)
                    if reg[1] is not None: reg[1] = int(reg[1])
                    if reg[2] is not None: reg[2] = int(reg[2])
                    for read in stream.fetch(*reg):
                        row = [self.filehandle.getrname(read.tid),
                               read.pos, read.pos+read.rlen,
                               read.mapq, read.qname, (-1 if read.is_reverse else 1),
                               read.flag, read.seq, read.qual, read.cigar, read.tags,
                               (0 if not read.is_paired else (1 if read.is_read1 else 2)),]
                        yield tuple([row[n] for n in srcl])
                self.close()
            return FeatureStream(_bamrecord(self.filehandle,srcl),fields)

        def write(self, source, fields, **kw):
            raise NotImplementedError("Writing to bam is not implemented.")

        def pileup(self,*args,**kwargs):
            self.open()
            if 'max_depth' not in kwargs: kwargs['max_depth'] = 100000
            return self.filehandle.pileup(*args,**kwargs)

        def fetch(self,*args,**kwargs):
            self.open()
            return self.filehandle.fetch(*args,**kwargs)

        def count(self, regions, on_strand=False, strict=True, readlen=None):
            """
            Counts the number of reads falling in a given set of *regions*.
            Returns a FeatureStream with one element per region, its score being the number of reads
            overlapping (even partially) this region.

            :param regions: any iterable over of tuples of the type `(chr,start,end)`.
            :param on_strand: (bool) restrict to reads on same strand as region.
            :param strict: (bool) restrict to reads entirely contained in the region.
            :param readlen: (int) set readlen if strict == True.
            :rtype: FeatureStream with fields (at least) ['chr','start','end','score'].
            """
            class Counter(object):
                def __init__(self,_o,_s,_r,_l):
                    self.n = 0
                    self.on_str = _o
                    self.strict = _s
                    self.reg = _r
                    self.len = _l
                def __call__(self, alignment):
                    if self.strict and \
                            (alignment.pos < self.reg[0] or \
                                 alignment.pos+(self.len or alignment.rlen) > self.reg[1]):
                        return
                    if self.on_str and \
                            (alignment.is_reverse and self.reg[2]>0) or \
                            (not alignment.is_reverse and self.reg[2]<0):
                        return
                    self.n += 1

            self.open()
            if isinstance(regions,FeatureStream):
                _f = [x for x in regions.fields]
                if 'score' not in _f: _f.append('score')
                _sci = _f.index('score')
                _sti = _f.index('strand') if 'strand' in _f else -1
            else:
                if on_strand:
                    _f = ['chr','start','end','strand','score']
                    _sci = 4
                    _sti = 3
                else:
                    _f = ['chr','start','end','score']
                    _sci = 3
                    _sti = -1
            def _count(regions):
                c = Counter(on_strand,strict,None,readlen)
                for x in regions:
                    c.n = 0
                    if _sti > 0: c.reg = x[1:3]+(x[_sti],)
                    else: c.reg = x[1:3]+(0,)
                    self.fetch(*x[:3], callback=c)
                    #The callback (c.n += 1) is executed for each alignment in a region
                    yield x[:_sci]+(c.n,)+x[_sci+1:]
                self.close()
            return FeatureStream(_count(regions),fields=_f)

        def coverage(self, region, strand=None):
            """
            Calculates the number of reads covering each base position within a given *region*.
            Returns a FeatureStream where the score is the number of reads overlapping this position.

            :param region: tuple `(chr,start,end)`. `chr` has to be
                present in the BAM file's header. `start` and `end` are 0-based
                coordinates, counting from the beginning of feature `chr`.
            :strand: if not None, computes a strand-specific coverage ('+' or 1 for forward strand,
                '-' or -1 for reverse strand).
            :rtype: FeatureStream with fields ['chr','start','end','score'].
            """
            self.open()
            if strand is not None:
##### mask=16 (=0x10): mask reads with "is_reverse" flag set
                pplus = self.pileup(*region,mask=16)
                if str(strand) in ['-','-1']:
##### pysam can't iterate simultaneously on 2 pileups from the same file!
                    pplus = iter([(x.pos,x.n) for x in pplus])
            pboth = self.pileup(*region)
            chr,start,end = region
            _f = ['chr','start','end','score']

            def _coverage(pboth,pplus=None):
                s = start
                e = start
                score = 0
                score1 = 0
                if pplus is None:
                    p1 = (end,0)
                else:
                    p1 = pplus.next()
                for p0 in pboth:
                    if p0.pos < s: continue
                    if p0.pos >= end: break
                    while p0.pos >= p1[0]:
                        try:
                            score1 = p1[1]
                            p1 = pplus.next()
                        except StopIteration:
                            p1 = (end,0)
                    if p0.pos == e+1 and p0.n-score1 == score:
                        e += 1
                    else:
                        if score > 0: yield (chr,s,e+1,score)
                        s = p0.pos
                        e = s
                        score = p0.n-score1
                if score > 0:
                    yield (chr,s,e+1,score)
                self.close()
            if str(strand) in ['+','1']:
                return FeatureStream(_coverage(pplus), fields=_f)
            elif str(strand) in ['-','-1']:
                return FeatureStream(_coverage(pboth,pplus), fields=_f)
            else:
                return FeatureStream(_coverage(pboth), fields=_f)

        def PE_fragment_size(self, region, midpoint=False, end=False):
            """
            Retrieves fragment sizes from paired-end data, and returns a bedgraph-style track::

                (chr,start,end,score) = genomic coordinates, average fragment size covering the coordinate

            :param region: tuple `(chr,start,end)`. `chr` has to be
                present in the BAM file's header. `start` and `end` are 0-based
                coordinates, counting from the beginning of feature `chr` and can be omitted.
            :param midpoint: attribute length to fragment midpoint (as opposed to all positions within fragment)
            :param end: attribute length to fragment left or right end (by setting end="left" or end="right")
            :rtype: FeatureStream with fields ['chr','start','end','score'].
            """
            def _frag_cover(region):
                self.open()
                _buff = {}
                for read in self.fetch(*region[:3]):
                    if read.is_reverse or not read.is_proper_pair or read.isize<0:
                        continue
                    flen = read.isize
                    if end == "left":
                        posrange = (read.pos,)
                    elif end == "right":
                        posrange = (read.pos+flen,)
                    elif midpoint:
                        posrange = (read.pos+flen/2,)
                    else:
                        posrange = range(read.pos,read.pos+flen)
                    for p in posrange:
                        if p in _buff: _buff[p].append(flen)
                        else: _buff[p] = [flen]
                    for p in sorted(_buff.keys()):
                        if p >= read.pos: break
                        fraglen = _buff.pop(p)
                        score = sum(fraglen)/float(len(fraglen))
                        yield (p,score)
                for p in sorted(_buff.keys()):
                    fraglen = _buff[p]
                    score = sum(fraglen)/float(len(fraglen))
                    yield (p,score)
                self.close()

            def _join(stream,chrom):
                start = -1
                end = -1
                score = 0
                for x in stream:
                    if x[0] == end and x[1] == score: end += 1
                    else:
                        if end>start: yield (chrom,start,end,score)
                        start, score = x
                        end = start+1
                if end>start: yield (chrom,start,end,score)

            if isinstance(region,basestring): region = [region]
            if isinstance(region,(list,tuple)):
                if len(region) < 3:
                    chrom = region[0]
                    region = [chrom, 0, self.chrmeta[chrom]['length']]
            else:
                raise ValueError("Region must be list ['chr',start,end] or string 'chr'.")
            return FeatureStream( _join(_frag_cover(region), region[0]),
                                  fields=['chr','start','end','score'] )


except ImportError: print "Warning: 'pysam' not installed, 'bam' format unavailable."

