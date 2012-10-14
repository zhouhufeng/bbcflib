"""
======================
Module: bbcflib.genrep
======================

This module provides an interface to GenRep repositories.
It provides two classes: the ``Assembly`` class provides a representation of a particular entry in GenRep,
the ``GenRep`` class allows to switch to any potential GenRep repository and
handles all queries. To retrieve an ``Assembly`` named ``ce6``, we write::

    from bbcflib import genrep
    a = genrep.Assembly( assembly='ce6' )

To switch to another instance of genrep::

    g = genrep.GenRep( url=my_url, root=my_path )
    if g.assemblies_available( 'ce6' ):
        a = genrep.Assembly( assembly='ce6', genrep=g )

Assemblies in GenRep are also assigned unique integer IDs.  The unique
integer ID for assembly ``ce6`` is 14.  We can use these IDs anywhere
we would use the name, so the third line in the prevous code could
equally well be written::

    a = genrep.Assembly(14)

"""

# Built-in modules #
import urllib2, json, os, re, tarfile
from datetime import datetime
from operator import itemgetter

# Internal modules #
from bbcflib.common import normalize_url, unique_filename_in
from bbcflib import btrack as track
from bbcflib.bFlatMajor.common import shuffled as track_shuffle

# Other modules #
import sqlite3

# Constants #
default_url = 'http://bbcf-serv01.epfl.ch/genrep/'
default_root = '/db/genrep'

################################################################################
class Assembly(object):
    def __init__(self, assembly=None, genrep=None, intype=0):
        """
        A representation of a GenRep assembly.
        To get an assembly from the repository, call the Assembly
        constructor with either the integer assembly ID or the string assembly
        name.  This returns an Assembly object::

            a = Assembly(3)
            b = Assembly('mm9')

        An Assembly has the following fields:

        .. attribute:: id

        An integer giving the assembly ID in GenRep.

        .. attribute:: name

        A string giving the nameassembly of the assembly in GenRep.

        .. attribute:: index_path

        The absolute path to the bowtie index for this assembly.

        .. attribute:: chromosomes

        A dictionary of chromosomes in the assembly.  The dictionary
        values are tuples of the form (chromsome id, RefSeq locus,
        RefSeq version), and the values are dictionaries with the keys
        'name' and 'length'.

        .. attribute:: bbcf_valid

        Boolean.

        .. attribute:: updated_at

        .. attribute:: created_at

        ``datetime`` objects.

        .. attribute:: nr_assembly_id

        .. attribute:: genome_id

        .. attribute:: source_id

        .. attribute:: intype

        All integers. ``intype`` is '0' for genomic data, '1' for exons and '2' for transcripts.

        .. attribute:: source_name

        .. attribute:: md5

        """
        if genrep is None: genrep = GenRep()
        self.genrep = genrep
        self.intype = int(intype)
        if not(assembly is None):
            self.set_assembly(assembly)

    def set_assembly(self, assembly):
        """
        Reset the Assembly attributes to correspond to *assembly*.

        :param assembly: integer giving the assembly ID, or a string giving the assembly name.
        """
        try:
            assembly = int(assembly)
            assembly_info = json.load(urllib2.urlopen(urllib2.Request(
                            """%s/assemblies/%d.json""" % (self.genrep.url, assembly))))
            chromosomes = json.load(urllib2.urlopen(urllib2.Request(
                            """%s/chromosomes.json?assembly_id=%d""" %(self.genrep.url, assembly))))
        except:
            try:
                url = """%s/assemblies.json?assembly_name=%s""" %(self.genrep.url, assembly)
                assembly_info = json.load(urllib2.urlopen(urllib2.Request(url)))[0]
            except IndexError: raise ValueError("URL not found: %s." % url)
            chromosomes = json.load(urllib2.urlopen(urllib2.Request(
                            """%s/chromosomes.json?assembly_name=%s""" %(self.genrep.url, assembly))))
        self._add_info(**dict((str(k),v) for k,v in assembly_info['assembly'].iteritems()))
        root = os.path.join(self.genrep.root,"nr_assemblies/bowtie")
        if self.intype == 1:
            root = os.path.join(self.genrep.root,"nr_assemblies/exons_bowtie")
        elif self.intype == 2:
            root = os.path.join(self.genrep.root,"nr_assemblies/cdna_bowtie")
        self.index_path = os.path.join(root,self.md5)
        for c in chromosomes:
            chrom = dict((str(k),v) for k,v in c['chromosome'].iteritems())
            cnames = chrom.pop('chr_names')
            chrom['name'] = (str(x['chr_name']['value']) for x in cnames \
                             if x['chr_name']['assembly_id'] == self.id).next()
            self._add_chromosome(**chrom)
        return None

    def _add_info(self, **kwargs):
        self.__dict__.update(kwargs)
        self.created_at = datetime.strptime(self.created_at,'%Y-%m-%dT%H:%M:%SZ')
        self.updated_at = datetime.strptime(self.updated_at,'%Y-%m-%dT%H:%M:%SZ')
        self.source_name = str(self.source_name)
        self.md5 = str(self.md5)
        self.chromosomes = {}

    def _add_chromosome(self, **kwargs):
        chr_keys = ['id','refseq_locus','refseq_version']
        key = tuple([kwargs[k] for k in chr_keys])
        self.chromosomes[key] = dict((k,kwargs[k]) for k in kwargs.keys() if not(k in chr_keys))

    def map_chromosome_names(self, names):
        """
        Finds keys in the `chromosomes` dictionary that corresponds to the names or ids given as `names`.
        Returns a dictionary, such as::

            assembly.map_chromosome_names([3,5,6,47])

            {'3': (2701, u'NC_001135', 4),
            '47': None,
            '5': (2508, u'NC_001137', 2),
            '6': (2580, u'NC_001138', 4)}

        """
        if not(isinstance(names,(list,tuple))):
            names = [names]
        url = "%s/chromosomes.json?assembly_name=%s&identifier=" %(self.genrep.url,self.name)
        mapped = {}
        chr_keys = ['id','refseq_locus','refseq_version']
        for n in names:
            chr_info = json.load(urllib2.urlopen(urllib2.Request(url+str(n))))
            if len(chr_info):
                mapped[str(n)] = tuple([chr_info[0]["chromosome"][k] for k in chr_keys])
            else:
                mapped[str(n)] = None
        return mapped

    def get_links(self,params):
        """
        Returns urls to features. Example::

            assembly.get_links({'name':'ENSMUSG00000085692', 'type':'gene'})

        returns the dictionary
        ``{"Ensembl":"http://ensembl.org/Mus_musculus/Gene/Summary?g=ENSMUSG00000085692"}``.
        If *params* is a string, then it is assumed to be the *name* parameter with ``type=gene``.
        """
        if isinstance(params,basestring):
            params = {'name':str(params),'type':'gene'}
        request = "&".join(["md5=%s"%self.md5]+[k+"="+v for k,v in params.iteritems()])
        url = urllib2.urlopen(urllib2.Request(
                """%s/nr_assemblies/get_links/%s.json?%s""" %(self.genrep.url,self.nr_assembly_id,request)))
        return url.read()

    def fasta_from_regions(self, regions, out=None, path_to_ref=None, chunk=50000, shuffled=False):
        """
        Get a fasta file with sequences corresponding to the features in the
        bed or sqlite file.

        Returns the name of the output file and the total size of the extracted sequence.

        :param regions: (str or dict or list) bed or sqlite file name, or sequence of features.
            If *regions* is a dictionary {'chr': [[start1,end1],[start2,end2]]}
            or a list [['chr',start1,end1],['chr',start2,end2]],
            will simply iterate through its items instead of loading a track from file.
        :param out: (str, filehandle or dict) output file name or filehandle.
            If *out* is a (possibly empty) dictionary, will return the updated dictionary.
        :param path_to_ref: (str or dict) path to a fasta file containing the whole reference sequence,
            or a dictionary {chr_name: path} as returned by Assembly.untar_genome_fasta.
        :rtype: (str,int)
        """
        if out is None: out = unique_filename_in()
        _to_close = False
        if isinstance(out,basestring):
            _to_close = True
            out = open(out,"w")

        def _push_slices(slices,start,end,name,cur_chunk):
            """Add a feature to *slices*, and increment the buffer size *cur_chunk* by the feature's size."""
            if end>start:
                slices['coord'].append([start,end])
                slices['names'].append(name)
                cur_chunk += end-start
            return slices,cur_chunk

        def _flush_slices(slices,chrid,chrn,out,path_to_ref):
            """Write the content of *slices* to *out*."""
            names = slices['names']
            coord = slices['coord']
            if isinstance(out,file):
                for i,s in enumerate(self.genrep.get_sequence(chrid,coord,path_to_ref=path_to_ref)):
                    if s: out.write(">"+names[i]+"|"+chrn+":"+str(coord[i][0])+"-"+str(coord[i][1])+"\n"+s+"\n")
            else:
                out[chrn].extend([s for s in self.genrep.get_sequence(chrid,coord,path_to_ref=path_to_ref)])
            return {'coord':[],'names':[]}

        slices = {'coord':[],'names':[]}
        size = 0
        if isinstance(regions,list): # convert to a dict
            reg_dict = {}
            for reg in regions:
                chrom = reg[0]
                if not(chrom in reg_dict):
                    reg_dict[chrom] = []
                reg_dict[chrom].append(reg[1:])
            regions = reg_dict
        if isinstance(regions,dict):
            cur_chunk = 0
            for cid,chrom in self.chromosomes.iteritems():
                if not(chrom['name'] in regions): continue
                if isinstance(out,dict): out[chrom['name']] = []
                if isinstance(path_to_ref,dict): pref = path_to_ref.get(chrom['name'])
                else: pref = path_to_ref
                for row in regions[chrom['name']]:
                    s = max(row[0],0)
                    e = min(row[1],chrom['length'])
                    slices,cur_chunk = _push_slices(slices,s,e,self.name,cur_chunk)
                    if cur_chunk > chunk:
                        size += cur_chunk
                        slices = _flush_slices(slices,cid[0],chrom['name'],out,pref)
                        cur_chunk = 0
                size += cur_chunk
                slices = _flush_slices(slices,cid[0],chrom['name'],out,pref)
        else:
            with track.track(regions, chrmeta=self.chrmeta) as t:
                _f = [f for f in ["start","end","name"] if f in t.fields]
                cur_chunk = 0
                for cid,chrom in self.chromosomes.iteritems():
                    if isinstance(path_to_ref,dict): pref = path_to_ref.get(chrom['name'])
                    else: pref = path_to_ref
                    features = t.read(selection=chrom['name'],fields=_f)
                    if shuffled:
                        features = track_shuffle( features, chrlen=chrom['length'],
                                                  repeat_number=1, sorted=False )
                    for row in features:
                        s = max(row[0],0)
                        e = min(row[1],chrom['length'])
                        name = re.sub('\s+','_',row[2]) if len(row)>2 else chrom['name']
                        slices,cur_chunk = _push_slices(slices,s,e,name,cur_chunk)
                        if cur_chunk > chunk: # buffer is full, write
                            size += cur_chunk
                            slices = _flush_slices(slices,cid[0],chrom['name'],out,pref)
                            cur_chunk = 0
                    size += cur_chunk
                    slices = _flush_slices(slices,cid[0],chrom['name'],out,pref)
        if _to_close: out.close()
        return (out,size)

    def statistics(self, output=None, frequency=False, matrix_format=False):
        """
        Return (di-)nucleotide counts or frequencies for an assembly, writes in file *output* if provided.
        Example of result::

            {
                "TT": 13574667
                "GG": 3344762
                "CC": 3365555
                "AA": 13571722
                "A": 32370285
                "TA": 6362526
                "GT": 4841536
                "AC": 4846697
                "N": 0
                "C": 17781115
                "TC": 6228639
                "GA": 6231575
                "CG": 3131283
                "GC: 3340219
                "CT": 5079814
                "AG": 5075950
                "G": 17758095
                "TG": 6206098
                "CA": 6204462
                "AT": 8875914
                "T": 32371931
            }

            Total = A + T + G + C

        If *matrix_format* is True, *output* is like::

             >Assembly: sacCer2
            1   0.309798640038793   0.308714120881750   0.190593944221299   0.190893294858157
        """
        request = urllib2.Request("%s/nr_assemblies/%d.json?data_type=counts" % (self.genrep.url, self.nr_assembly_id))
        stat    = json.load(urllib2.urlopen(request))
        total   = float(stat["A"]+stat["T"]+stat["G"]+stat["C"])
        if frequency:
            stat = dict((k,x/total) for k,x in stat.iteritems())
        else:
            stat.update
        if output == None:
            return stat
        else:
            with open(output, "w") as f:
                if matrix_format:
                    f.write(">Assembly: %s\n" % self.name)
                    f.write("%s\t%s\t%s\t%s" %(stat["A"],stat["C"],stat["G"],stat["T"]))
                    f.write("\n")
                else:
                    f.write("#Assembly: %s\n" % self.name)
                    [f.write("%s\t%s\n" % (x,stat[x])) for x in ["A","C","G","T"]]
                    f.write("#\n")
                    [[f.write("%s\t%s\n" % (x+y,stat[x+y])) for y in ["A","C","G","T"]] for x in ["A","C","G","T"]]
            return output

    def fasta_path(self, chromosome=None):
        """Return the path to the compressed fasta file, for the whole assembly or for a single chromosome."""
        root = os.path.join(self.genrep.root,"nr_assemblies/fasta")
        path = os.path.join(root,self.md5+".tar.gz")
        if chromosome != None:
            chr_id = str(chromosome[0])+"_"+str(chromosome[1])+"."+str(chromosome[2])
            root = os.path.join(self.genrep.root,"chromosomes/fasta")
            path = os.path.join(root,chr_id+".fa.gz")
        elif self.intype == 1:
            root = os.path.join(self.genrep.root,"nr_assemblies/exons_fasta")
            path = os.path.join(root,self.md5+".fa.gz")
        elif self.intype == 2:
            root = os.path.join(self.genrep.root,"nr_assemblies/cdna")
            path = os.path.join(root,self.md5+".fa.gz")
        return path

    def untar_genome_fasta(self, path_to_ref=None, convert=True):
        """Untar and concatenate reference sequence fasta files.
        Returns a dictionary {chr_name: file_name}

        :param assembly: the GenRep.Assembly instance of the species of interest.
        :param convert: (bool) True if chromosome names need conversion from id to chromosome name.
        """
        if path_to_ref is None: path_to_ref = self.fasta_path()
        if not(os.path.exists(path_to_ref)): return None
        if convert:
            # Create a dict of the form {'2704_NC_001144.4': chrXII}
            chrlist = dict((str(k[0])+"_"+str(k[1])+"."+str(k[2]),v['name'])
                           for k,v in self.chromosomes.iteritems())
        else:
            chrlist = {}
        archive = tarfile.open(path_to_ref)
        genomeRef = {}
        for f in archive.getmembers():
            if f.isdir(): continue
            inf = archive.extractfile(f)
            header = inf.readline()
            headpatt = re.search(r'>(\S+)\s',header)
            if headpatt: chrom = headpatt.groups()[0]
            else: continue
            if convert and chrom in chrlist:
                header = re.sub(chrom,chrlist[chrom],header)
                chrom = chrlist[chrom]
            genomeRef[chrom] = unique_filename_in()
            with open(genomeRef[chrom],"wb") as outf:
                outf.write(header)
                [outf.write(l) for l in inf]
            inf.close()
        archive.close()
        return genomeRef

    def get_sqlite_url(self):
        """Return the url of the sqlite file containing gene annotations."""
        return '%s/data/nr_assemblies/annot_tracks/%s.sql' %(self.genrep.url, self.md5)

    def sqlite_path(self):
        """Return the path to the sqlite file containing genes annotations."""
        root = os.path.join(self.genrep.root,"nr_assemblies/annot_tracks")
        return os.path.join(root,self.md5+".sql")

    def get_features_from_gtf(self,h,chr=None,method="dico"):
        """
        Return a dictionary *data* of the form
        ``{key:[[values],[values],...]}`` containing the result of an SQL request which
        parameters are given as a dictionary *h*. All [values] correspond to a line in the SQL.

        :param chr: (str, or list of str) chromosomes on which to perform the request. By default,
        every chromosome is searched.

        Available keys for *h*, and possible values:

        * "keys":       "$,$,..."            (fields to `SELECT` and pass as a key of *data*)
        * "values":     "$,$,..."            (fields to `SELECT` and pass as respective values of *data*)
        * "conditions": "$:#,$:#,..."        (filter (SQL `WHERE`))
        * "uniq":       "whatever"           (SQL `DISTINCT` if specified, no matter what the -string- value is)
        * "at_pos":     "12,36,45,1124,..."  (to select only features overlapping this list of positions)

        where

        * $ holds for any column name in the database
        * # holds for any value in the database

        Note: giving several field names to "keys" permits to select unique combinations of these fields.
        The corresponding keys of *data* are a concatenation (by ';') of these fields.
        """
        data = {}
        if isinstance(chr,list): chromosomes = chr
        elif isinstance(chr,str): chromosomes = chr.split(',')
        else: chromosomes = [None]
        if not(method in ["dico","boundaries"]): return data
        # Sqlite3 request to /db/
        dbpath = self.sqlite_path()
        if os.path.exists(dbpath) and not h.get('at_pos'):
            if chromosomes == [None]: chromosomes = self.chrnames
            db = sqlite3.connect(dbpath)
            cursor = db.cursor()
            dist = h.get('uniq','') and "DISTINCT "
            for chrom in chromosomes:
                if method == 'dico':
                    sql = "SELECT "+dist+",".join(h['keys'].split(',')+h['values'].split(','))
                    sql += " FROM '%s'" %chrom
                else:
                    h['names'] = ",".join([x for x in h['names'].split(',') if not(x == 'chr_name')])
                    sql = "SELECT "+dist+"MIN(start),MAX(end),"+h['names']
                    sql += " FROM '%s'" %chrom
                if h.get('conditions'):
                    sql += " WHERE "
                    conditions = []
                    for c in h['conditions'].split(','):
                        k,v = c.split(':')
                        if "|" in v:
                            conditions.append( "(%s in ('%s'))"%(k,"','".join(v.split("|"))) )
                        else:
                            conditions.append( "(%s='%s')"%(k,v) )
                    sql += " AND ".join(conditions)
                if method == 'boundaries':
                    sql += " GROUP BY "+h['names']
                cursor.execute(sql)
                for x in cursor:
                    if 'names' in h:
                        key = ';'.join([str(_) for _ in x[2:]]+[chrom])
                        values = list(x[:2])
                    else:
                        nkeys = len(h['keys'].split(','))
                        key = ';'.join([str(_) for _ in x[:nkeys]])
                        values = list(x[nkeys:]+(chrom,))
                    data.setdefault(key,[]).append(values)
        # Genrep url request
        else:
            for chrom in chromosomes:
                request = self.genrep.url+"/nr_assemblies/get_%s?md5=%s" %(method,self.md5)
                request += "&".join(['']+["%s=%s" %(k,v) for k,v in h.iteritems()])
                if chrom: request += "&chr_name="+chrom
                data.update(json.load(urllib2.urlopen(request)))
        return data

    def get_gene_mapping(self):
        """
        Return a dictionary ``{gene_id: (gene_name,start,end,length,strand,chromosome)}``
        Note that the gene's length is not the sum of the lengths of its exons.
        """
        gene_mapping = {}
        h = {"keys":"gene_id", "values":"gene_name,start,end,strand", "conditions":"type:exon", "uniq":"1"}
        for chr in self.chrnames:
            resp = self.get_features_from_gtf(h,chr)
            for k,v in resp.iteritems():
                start = min([x[1] for x in v])
                end = max([x[2] for x in v])
                name = str(v[0][0])
                strand = int(v[0][3])
                gene_mapping[str(k)] = (name,start,end,-1,strand,chr)
            # Find gene lengths
            length = fend = 0
            for g,exons in resp.iteritems():
                exons.sort(key=itemgetter(1,2)) # sort w.r.t. start, then end
                for x in exons:
                    start = x[1]; end = x[2]
                    if start >= fend:
                        length += end-start # new exon
                        fend = end
                    elif end <= fend: pass  # embedded exon
                    else:
                        length += end-fend  # overlapping exon
                        fend = end
                gmap = list(gene_mapping[str(g)])
                gmap[3] = length
                length = 0
                gene_mapping.update({str(g):tuple(gmap)})
                fend = 0
        return gene_mapping

    def get_transcript_mapping(self):
        """Return a dictionary ``{transcript_id: (gene_id,start,end,length,strand,chromosome)}``"""
        transcript_mapping = {}
        h = {"keys":"transcript_id", "values":"gene_id,start,end,strand", "conditions":"type:exon", "uniq":"1"}
        for chr in self.chrnames:
            resp = self.get_features_from_gtf(h,chr)
            for k,v in resp.iteritems():
                start = min([x[1] for x in v])
                end = max([x[2] for x in v])
                length = sum([x[2]-x[1] for x in v])
                gid = str(v[0][0])
                strand = int(v[0][3])
                transcript_mapping[str(k)] = (gid,start,end,length,strand,chr)
        return transcript_mapping

    def get_exon_mapping(self):
        """Return a dictionary ``{exon_id: ([transcript_id's],gene_id,gene_name,start,end,strand,chromosome)}``"""
        exon_mapping = {}
        h = {"keys":"exon_id", "values":"transcript_id,gene_id,gene_name,start,end,strand",
             "conditions":"type:exon", "uniq":"1"}
        for chr in self.chrnames:
            resp = self.get_features_from_gtf(h,chr)
            for k,v in resp.iteritems():
                start = int(v[0][3])
                end = int(v[0][4])
                tid = [str(x[0]) for x in v]
                gid = str(v[0][1])
                gname = str(v[0][2])
                strand = int(v[0][5])
                exon_mapping[str(k)] = (tid,gid,gname,start,end,strand,chr)
        return exon_mapping

    def get_exons_in_trans(self):
        """Return a dictionary ``{transcript_id: list of exon_id's it contains}``"""
        exons_in_trans = {}
        h = {"keys":"transcript_id", "values":"exon_id", "conditions":"type:exon", "uniq":"1"}
        data = self.get_features_from_gtf(h)
        for k,v in data.iteritems():
            exons_in_trans[str(k)] = [str(x[0]) for x in v]
        return exons_in_trans

    def get_trans_in_gene(self):
        """Return a dictionary ``{gene_id: list of transcript_id's it contains}``"""
        trans_in_gene = {}
        h = {"keys":"gene_id", "values":"transcript_id", "conditions":"type:exon", "uniq":"1"}
        data = self.get_features_from_gtf(h)
        for k,v in data.iteritems():
            trans_in_gene[str(k)] = [str(x[0]) for x in v]
        return trans_in_gene

    def gene_coordinates(self,id_list):
        """Creates a BED-style stream from a list of gene ids."""
        _fields = ['chr','start','end','name','score','strand']
        _ids = "|".join(id_list)
        sort_list = []
        webh = { "names": "gene_id,gene_name,strand,chr_name",
                 "conditions": "gene_id:%s" %_ids,
                 "uniq":"1" }
        resp = self.get_features_from_gtf(webh,method='boundaries')
        for k,v in resp.iteritems():
            for vv in v:
                start,end = vv
                gene_id,gene_name,strand,chr_name = [str(y).strip() for y in k.split(';')]
                name = "%s|%s" %(gene_id,gene_name)
                sort_list.append((chr_name,start,end,name,0,int(strand)))
        sort_list.sort()
        return track.FeatureStream(sort_list,fields=_fields)

    def annot_track(self,annot_type='gene',chromlist=None,biotype=["protein_coding"]):
        """
        Return an iterator over all annotations of a given type in the genome.

        :param annot_type: (str) one of 'gene','transcript','exon','CDS'.
        :chrom_list: (list of str) return only features in the specified chromosomes.
        :biotype: (list of str, or None) return only features with the specified biotype(s).
            If None, all biotypes are selected.
        :rtype: btrack.FeatureStream
        """
        if chromlist is None: chromlist = self.chrnames
        elif isinstance(chromlist,basestring): chromlist = [chromlist]
        _fields = ['chr','start','end','name','strand']
        nmax = 4
        if annot_type == 'gene':
            flist = "gene_id,gene_name,strand"
            webh = { "keys": "gene_id",
                     "values": "start,end,"+flist,
                     "conditions": "type:exon",
                     "uniq":"1" }
        elif annot_type in ['CDS','exon']:
            flist = "exon_id,gene_id,gene_name,strand,frame"
            webh = { "keys": "exon_id,start,end",
                     "values": "start,end,"+flist,
                     "conditions": "type:"+annot_type,
                     "uniq":"1" }
            nmax = 5
            _fields += ['frame']
        elif annot_type == 'transcript':
            flist = "transcript_id,gene_name,strand"
            webh = { "keys": "transcript_id",
                     "values": "start,end,"+flist,
                     "conditions": "type:exon",
                     "uniq":"1" }
        else:
            raise TypeError("Annotation track type '%s' not implemented." %annot_type)
        def _query():
            for chrom in chromlist:
                sort_list = []
                if biotype is not None:
                    for bt in biotype:
                        wh = webh.copy()
                        wh["conditions"]+=",biotype:"+bt
                        resp = self.get_features_from_gtf(wh,chrom)
                        for k,v in resp.iteritems():
                            start = min([x[0] for x in v])
                            end = max([x[1] for x in v])
                            name = "|".join([str(y) for y in v[0][2:nmax]])
                            sort_list.append((start,end,name)+tuple(v[0][nmax:]))
                else:
                    wh = webh
                    resp = self.get_features_from_gtf(wh,chrom)
                    for k,v in resp.iteritems():
                        start = min([x[0] for x in v])
                        end = max([x[1] for x in v])
                        name = "|".join([str(y) for y in v[0][2:nmax]])
                        sort_list.append((start,end,name)+tuple(v[0][nmax:]))
                sort_list.sort()
                for k in sort_list: yield (chrom,)+k[:-1]
        return track.FeatureStream(_query(),fields=_fields)

    def gene_track(self,chromlist=None,biotype=["protein_coding"]):
        """Return a FeatureStream over all protein coding genes annotation in the genome:
        ('chr', start, end, 'gene_id|gene_name', strand)."""
        return self.annot_track(annot_type='gene',chromlist=chromlist,biotype=biotype)

    def exon_track(self,chromlist=None,biotype=["protein_coding"]):
        """Return a FeatureStream over all coding exons annotation in the genome:
        ('chr', start, end, 'exon_id|gene_id|gene_name', strand, phase)."""
        return self.annot_track(annot_type='exon',chromlist=chromlist,biotype=biotype)

    def transcript_track(self,chromlist=None,biotype=["protein_coding"]):
        """Return a FeatureStream over all protein coding transcripts annotation in the genome:
        ('chr', start, end, 'gene_id|gene_name', strand)."""
        return self.annot_track(annot_type='transcript',chromlist=chromlist,biotype=biotype)

    @property
    def chrmeta(self):
        """
        Return a dictionary of chromosome meta data of the type:
        ``{'chr1': {'length': 249250621},'chr2': {'length': 135534747},'chr3': {'length': 135006516}}``
        """
        return dict([(v['name'], dict([('length', v['length']),
                                       ('ac',str(k[0])+"_"+str(k[1])+"."+str(k[2]) if k[1] else k[0])]))
                     for k,v in self.chromosomes.iteritems()])

    @property
    def chrnames(self):
        """Return a list of chromosome names."""
        namelist = [(v['num'],v['name']) for v in self.chromosomes.values()]
        return [x[1] for x in sorted(namelist)]

################################################################################
class GenRep(object):
    """
    Attributes:

    .. attribute:: url

        GenRep url ('genrep.epfl.ch').

    .. attribute:: root

        Path to GenRep indexes.
    """
    def __init__(self, url=None, root=None, config=None, section='genrep'):
        """
        Create an object to query a GenRep repository.

        GenRep is the in-house repository for sequence assemblies for the
        BBCF in Lausanne.  This is an object that wraps its use in Python
        in an idiomatic way.

        Create a GenRep object with the base URL to the GenRep system, and
        the root path of GenRep's files.  For instance::

            g = GenRep('genrep.epfl.ch', '/path/to/genrep/indices')

        To get an assembly from the repository, call the assembly
        method with either the integer assembly ID or the string assembly
        name.  This returns an Assembly object::

            a = g.assembly(3)
            b = g.assembly('mm9')

        You can also pass this to the Assembly call directly::

            a = Assembly(assembly='mm9',genrep=g)

        """
        if not(config is None):
            if url is None:
                url = config.get(section, 'genrep_url')
            if root is None:
                root = config.get(section, 'genrep_root')
        if url is None: url = default_url
        if root is None: root = default_root
        self.url = normalize_url(url)
        self.root = os.path.abspath(root)

    def assembly(self,assembly,intype=0):
        """Backward compatibility"""
        return Assembly( assembly=assembly, genrep=self, intype=intype )

    def is_up(self):
        """Check if genrep webservice is available"""
        try:
            urllib2.urlopen(self.url + "/nr_assemblies.json", timeout=2)
        except urllib2.URLError:
            return False
        return True

    def assemblies_available(self, assembly=None):
        """
        Return a list of assemblies available on genrep, or tells if an
        assembly with name *assembly* is available.
        """
        request = urllib2.Request(self.url + "/assemblies.json")
        assembly_list = []
        for a in json.load(urllib2.urlopen(request)):
            name = a['assembly'].get('name')
            if name == None: continue
            if name == assembly: return True
            assembly_list.append(name)
        if assembly == None: return assembly_list

    def get_sequence(self, chr_id, coord_list, path_to_ref=None):
        """Parse a slice request to the repository.

        :param chr_id: (int) chromosome number (keys of Assembly.chromosomes).
        :param coord_list: (list of (int,int)) sequences' (start,end) coordinates.
        :param path_to_ref: (str) path to a fasta file containing the whole reference sequence.
        """
        if len(coord_list) == 0:
            return []
        for k,c in enumerate(coord_list):
            if c[1] < c[0]: coord_list[k] = (c[1],c[0]) # end < start
            elif c[1] == c[0]: coord_list.pop(k)        # end = start
        coord_list = sorted(coord_list)
        # to do += make it work with gzip + tar files > 'decompress' function to bbcflib.common
        if path_to_ref and os.path.exists(path_to_ref):
            a = 0
            f = open(path_to_ref)
            sequences = []
            coord_list = iter(coord_list)
            start,end = coord_list.next()
            seq = ''
            line = True
            for i,line in enumerate(f):
                line = line.strip(' \t\r\n')
                if line.startswith('>'): continue
                b = a+len(line)
                while start <= b:
                    start = max(a,start)
                    if end <= b:
                        seq += line[start-a:end-a]
                        sequences.append(seq.upper())
                        seq = ''
                        try:
                            start,end = coord_list.next()
                        except StopIteration:
                            f.close()
                            return sequences
                    elif end > b:
                        seq += line[start-a:]
                        a = b
                        break
                a = b
            f.close()
            return sequences
        else:
            slices  = ','.join([','.join([str(y) for y in x]) for x in coord_list])
            url     = """%s/chromosomes/%i/get_sequence_part?slices=%s""" % (self.url, chr_id, slices)
            request = urllib2.Request(url)
            return urllib2.urlopen(request).read().split(',')

    def get_genrep_objects(self, url_tag, info_tag, filters = None, params = None):
        """
        Get a list of GenRep objets.

        :param url_tag: the GenrepObject type (plural)
        :param info_tag: the GenrepObject type (singular)
        :param filters: a dict that is used to filter the response
        :param params: to add some parameters to the query from GenRep.

        Example:

        To get the genomes related to 'Mycobacterium leprae' species::

            species = get_genrep_objects('organisms', 'organism', {'species':'Mycobacterium leprae'})[0]
            genomes = get_genrep_objects('genomes', 'genome', {'organism_id':species.id})
        """
        if not self.is_up(): return []
        if filters is None: filters = {}
        url = '%s/%s.json' % (self.url, url_tag)
        if params is not None:
            url += '?'
            url += '&'.join([k + '=' + v for k, v in params.iteritems()])
        infos = json.load(urllib2.urlopen(url))
        result = []
        for info in infos:
            obj = GenrepObject(info,info_tag)
            if not filters:
                result.append(obj)
            else:
                for k,v in filters.items():
                    if hasattr(obj,k) and getattr(obj,k) == v:
                        result.append(obj)
                        break
        return result

################################################################################
class GenrepObject(object):
    """
    Class wich will reference all different objects used by GenRep
    In general, you should never instanciate GenrepObject directly but
    call a method from the GenRep object.

    .. method:: __repr__()
    """
    def __init__(self, info, key):
        self.__dict__.update(info[key])

    def __repr__(self):
        return str(self.__dict__)

################################################################################

#-----------------------------------#
# This code was written by the BBCF #
# http://bbcf.epfl.ch/              #
# webmaster.bbcf@epfl.ch            #
#-----------------------------------#
