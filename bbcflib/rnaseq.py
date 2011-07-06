"""
======================
Module: bbcflib.rnaseq
======================

"""

# General modules #
import pickle, json, pysam, numpy, urllib, math
from itertools import combinations
from scipy import stats
from scipy.interpolate import UnivariateSpline
from rpy2 import robjects
import rpy2.robjects.packages as rpackages
import rpy2.robjects.numpy2ri
import rpy2.rlike.container as rlc

# Internal modules #
from bbcflib.mapseq import plot_stats, bamstats, map_groups, get_fastq_files
from bbcflib.daflims import DAFLIMS
from bbcflib.genrep import GenRep

# Don't do this #
from numpy import *
from bein.util import *

def fetch_transcript_mapping(ex, assembly_id):
    """Given an assembly ID, return a dictionary giving an exon to orf mapping.

    The *assembly_id* can be a string or integer.  If it is an
    integer, the mapping is looked up from GenRep.  Otherwise it is
    assumed to be a file containing a JSON object which is read to get
    the mapping.
    """
    nr_assemblies = urllib.urlopen("http://bbcftools.vital-it.ch/genrep/nr_assemblies.json").read()
    nr_assemblies = json.loads(nr_assemblies)
    for a in nr_assemblies:
        if a['nr_assembly']['id'] == assembly_id or a['nr_assembly']['name'] == assembly_id:
            mdfive = a['nr_assembly']['md5']; break

    if os.path.exists(str(mdfive) + '.pickle'):
        with open(str(mdfive) + '.pickle', 'rb') as pickle_file:
            mapping = pickle.load(pickle_file)
            return mapping
        print "Exon to ORF mapping found in", os.path.dirname(pickle_path)
    elif os.path.exists("/db/genrep/nr_assemblies/exons_pickle/"+str(mdfive)+".pickle"):
        with open("/db/genrep/nr_assemblies/exons_pickle/"+mdfive+".pickle") as pickle_file:
            mapping = pickle.load(pickle_file)
        return mapping
        print "Exon to ORF mapping found in /db/"
    else:
        genrep = GenRep('http://bbcftools.vital-it.ch/genrep/',
                        '/db/genrep/nr_assemblies/exons_pickle')
        assembly = genrep.assembly(mdfive)
        with open(assembly.index_path + '.pickle', 'rb') as pickle_file:
            mapping = pickle.load(pickle_file)
            return mapping
        print "Exon to ORF mapping found on GenRep"
        
def map_runs(fun, runs):
    """Parallelization of fun(run) executions"""
    futures = {}
    for group_id, run_list in runs.iteritems():
        futures[group_id] = [fun(run) for run in run_list]
    results = {}
    for group_id, future_list in futures.iteritems():
        results[group_id] = [f.wait() for f in future_list]
    return results

def exons_labels(bamfile):
    """List of the exons labels (SN: 'reference sequence name'; LN: 'sequence length') in *bamfile*."""
    sam = pysam.Samfile(bamfile, 'rb')
    labels = [(t['SN'],t['LN']) for t in sam.header['SQ']]
    sam.close()
    return labels

def pileup_file(bamfile, exons):
    """Return a numpy array of the pileup of *bamfile* in order *exons*."""
    counts = numpy.zeros(len(exons))
    sam = pysam.Samfile(bamfile, 'rb')

    class Counter(object):
        def __init__(self):
            self.n = 0
        def __call__(self, alignment):
            self.n += 1

    c = Counter()
    for i,exon in enumerate(exons):
        sam.fetch(exon[0], 0, exon[1], callback=c)
        counts[i] = c.n
        c.n = 0
    sam.close()
    return counts

def pairs_to_test(controls):
    """*controls* is a dictionary of group_ids to True/False.

    If all the values are True or all the values are False, then it
    returns all unique pairs of group IDs.  Otherwise it returns all
    combinations of one group ID with value True and one with value
    False.
    """
    if all(controls.values()) or not(any(controls.values())):
        return list(combinations(controls.keys(), 2))
    else:
        return [(x,y) for x in controls.keys() for y in controls.keys()
                if controls[x] and not(controls[y])]

@program
def external_deseq(cond1_label, cond1, cond2_label, cond2, transcript_names, method="normal",
                   assembly_id=None, output=None, maplot=None):
    if output:
        result_filename = output
    else:
        result_filename = unique_filename_in()
    c1 = unique_filename_in()
    with open(c1,'wb') as f:
        pickle.dump(cond1,f,pickle.HIGHEST_PROTOCOL)
    c2 = unique_filename_in()
    with open(c2,'wb') as f:
        pickle.dump(cond2,f,pickle.HIGHEST_PROTOCOL)
    tn = unique_filename_in()
    with open(tn,'wb') as f:
        pickle.dump(transcript_names,f,pickle.HIGHEST_PROTOCOL)
    call = ["run_deseq.py", c1, c2, tn, cond1_label, cond2_label, method, str(assembly_id), result_filename, str(maplot)]
    return {"arguments": call, "return_value": result_filename}

def results_to_json(lims, exid):
    """Create a JSON string describing the results of execution *exid*.

    The execution is sought in *lims*, and all its output files and
    their descriptions are written to the string.
    """
    produced_file_ids = lims.search_files(source=('execution',exid))
    d = dict([(lims.fetch_file(i)['description'], lims.path_to_file(i))
              for i in produced_file_ids])
    j = json.dumps(d)
    return j

def inference(cond1_label, cond1, cond2_label, cond2, transcript_names, method="normal",
              assembly_id=None, output=None, maplot=None):
    """Runs DESeq comparing the counts in *cond1* and *cond2*.

    Arguments *cond1* and *cond2* are lists of numpy arrays. Each
    array lists the number of reads mapping to a particular
    transcript. *cond1_label* and *cond2_label* are string which will
    be used to identify the two conditions in R.  *transcript_names*
    is a list of strings, in the same order as the numpy arrays, used
    to name the transcripts in R.

    ``deseq_inference`` writes a tab delimited text file of the
    conditions to R, the first column being the transcript name,
    followed by one column for each numpy array in *cond1*, then one
    column for each numpy array in *cond2*.

    Then it calls DESeq in R, writes out the results in a new,
    randomly named file, and returns that filename.
    """
    ### FAILS IF TOO FEW READS

    # Pass the data into R as a data frame
    data_frame_contents = rlc.OrdDict([(cond1_label+'-'+str(i), robjects.IntVector(c))
                                       for i,c in enumerate(cond1)] +
                                      [(cond2_label+'-'+str(i), robjects.IntVector(c))
                                       for i,c in enumerate(cond2)])
    data_frame = robjects.DataFrame(data_frame_contents)
    data_frame.rownames = transcript_names
    conds = robjects.StrVector([cond1_label for x in cond1] + [cond2_label for x in cond2]).factor()

    ## DESeq full analysis
    deseq = rpackages.importr('DESeq')
    cds = deseq.newCountDataSet(data_frame, conds)
    cds = deseq.estimateSizeFactors(cds)
    cds = deseq.estimateVarianceFunctions(cds,method=method)
    res = deseq.nbinomTest(cds, cond1_label, cond2_label)

    ## Replace (unique) gene IDs by (not unique) gene names

    if assembly_id:
        if isinstance(assembly_id,str):
            nr_assemblies = urllib.urlopen("http://bbcftools.vital-it.ch/genrep/nr_assemblies.json").read()
            nr_assemblies = json.loads(nr_assemblies)
            for a in nr_assemblies:
                if a['nr_assembly']['name'] == assembly_id:
                    assembly_id = a['nr_assembly']['id']; break
        print "Translate gene IDs to gene names..."
        res_ids = list(res[0])
        idtoname = {}; res_names = []; gid = None; l = None
        (assem,headers) = urllib.urlretrieve("http://bbcftools.vital-it.ch/genrep/nr_assemblies/" + str(assembly_id) + ".gtf")
        with open(assem) as assembly:
            for l in [line for line in assembly.readlines() if line.find("gene_name")!=-1]:
                gid = l.split("gene_id")[1].split(";")[0].strip(" \"")
                gname = l.split("gene_name")[1].split(";")[0].strip(" \"")
                idtoname[gid] = gname
        urllib.urlcleanup()
        for i in res_ids:
            res_names.append(idtoname.get(i, i))
        data_frame = robjects.DataFrame({"GeneName":robjects.StrVector(res_names)})
        for i in range(2,len(res)+1):
            data_frame = data_frame.cbind(res.rx(i))
        res = data_frame

    ## MA-plot
    if maplot:
        MAplot(res, mode=maplot)

    if output:
        result_filename = output
    else:
        result_filename = unique_filename_in()

    res.to_csvfile(result_filename)
    return result_filename

def rnaseq_workflow(ex, job, assembly, via="lsf", output=None, maplot="normal", with_exons=None):
    """Run RNASeq inference according to *job_info*.

    output: alternative name for output file. Otherwise it is random.
    maplot: MA-plot of data.
            If "interactive", one can click on a point (gene or exon) to display its name;
            if "normal", name of genes over 99.9%/under 0.1% quantiles are displayed;
            if None, no figure is produced.
    with_exons: run inference (DESeq) on exon mapping in addition to gene mapping.

    Whatever script calls this function should have looked up the job
    description from HTSStation.  The job description from HTSStation
    is returned as Job object (or a dictionary of the same form),
    which is what ``workflow`` expects.
    The object must have the fields:

        * ``assembly_id``, which ``path_to_bowtie_index`` uses to get
          a path from GenRep.

        * ``groups``, a dictionary of the conditions, and the
          information to fetch the files corresponding to those
          conditions from the DAF LIMS.

    If ``assembly_id`` is a string, not an integer, than it is
    interpreted as a path to the bowtie index, and no lookup to GenRep
    is necessary.

    Likewise, if the values of ``groups`` are lists of
    strings, then they are interpreted as a list of filenames and no
    lookup is done on the DAF LIMS.

    Whatever script calls workflow needs to pass back the JSON string
    it returns in some sensible way.  For the usual HTSStation
    frontend, this just means printing it to stdout.
    """
            
    names = {}; runs = {}; controls = {}; paths = {}; gids = {}
    groups = job.groups
    assembly_id = job.assembly_id
    for i,group in groups.iteritems():
        names[i] = str(group['name'])
        runs[i] = group['runs'].values()
        controls[i] = group['control']

    fastq_root = os.path.abspath(ex.working_directory)
    bam_files = map_groups(ex, job, fastq_root, assembly_or_dict = assembly)
    print "Reads aligned."

    # gene_labels is a list whose i-th entry is a string giving
    # the name of the gene assigned id i. The ids are arbitrary.
    # exon_mapping is a list whose i-th entry is the integer id in
    # gene_labels exon i maps to.
    (gene_labels,exon_mapping) = fetch_transcript_mapping(ex, assembly_id)
    exon_mapping = numpy.array(exon_mapping)
    # All the bam_files were created against the same index, so
    # they all have the same header in the same order.  I can take
    # the list of exons from just the first one and use it for all
    # of them
    exons = exons_labels(bam_files.values()[0][1]['bam'])

    exon_pileups = {}; gene_pileups = {}
    for condition,files in bam_files.iteritems():
        gene_pileups[condition] = []
        exon_pileups[condition] = []
        for f in files.values():
            exon_pileup = pileup_file(f['bam'], exons)
            exon_pileups[condition].append(exon_pileup)
            gene_pileup = numpy.zeros(len(gene_labels))
            for i,c in enumerate(exon_pileup):
                gene_pileup[exon_mapping[i]] += c
            gene_pileups[condition].append(gene_pileup)

    futures = {}
    for (c1,c2) in pairs_to_test(controls):
        if len(runs[c1]) + len(runs[c2]) > 2:
            method = "normal";
        else: method = "blind";

        if with_exons:
            print "Inference (genes+exons)..."
            futures[(c1,c2)] = [external_deseq.nonblocking(ex,
                                      names[c1], exon_pileups[c1],
                                      names[c2], exon_pileups[c2],
                                      [x[0].split("|")[0]+"|"+x[0].split("|")[1] for x in exons],
                                      method, assembly_id, output, maplot, via=via),
                                external_deseq.nonblocking(ex,
                                      names[c1], gene_pileups[c1],
                                      names[c2], gene_pileups[c2],
                                      gene_labels,
                                      method, assembly_id, output, maplot,via=via)]
            print "Wait for results....."
            for c,f in futures.iteritems():
                ex.add(f[0].wait(),
                       description="Comparison of exons in conditions '%s' and '%s' (CSV)" % (names[c[0]], names[c[1]]))
                ex.add(f[1].wait(),
                       description="Comparison of genes in conditions '%s' and '%s' (CSV)" % (names[c[0]], names[c[1]]))
        else:
            print "Inference (genes only)..."
            csvfile = external_deseq.nonblocking(ex,
                                    names[c1], gene_pileups[c1],
                                    names[c2], gene_pileups[c2],
                                    gene_labels,
                                    method, assembly_id, output, maplot, via=via)
            print "    Wait for results..."
            ex.add(csvfile.wait(),
                   description="Comparison of exons in conditions '%s' and '%s' (CSV)" % (names[c1], names[c2]))
        print "Done."

        if maplot: ex.add("MAplot.png", description="MA-plot of data")


def MAplot(data, mode="normal", deg=2, bins=30):
    """
    Creates an "MA-plot" to compare transcription levels of a set of genes
    in two different conditions. It returns a list of triplets (name, x, y) for each point,
    and a dictionary containing a list of couples for each quantile spline, each couple (xs,ys)
    being a point the corresponding spline passes through. Input:

    data: rpy DataFrame object; two columns, each for a different condition.
    mode: if "interactive", click on a point to display its name;
          if "normal", name of genes over 99%/under 1% quantile are displayed.
    """

    #####
    # TO IMPLEMENT:
    # - Groups of genes
    #####

    import matplotlib.pyplot as plt

    if isinstance(data[0],rpy2.robjects.vectors.FactorVector):
        a = array(data[0])
        b = array(data[0].levels)
        names = list(b[a-1])
        d1 = array(data[1])
        d2 = array(data[2])
    elif isinstance(data[0],rpy2.robjects.vectors.StrVector):
        names = list(data[0])
        d1 = array(data[1])
        d2 = array(data[2])
    elif isinstance(data[0],rpy2.robjects.vectors.FloatVector):
        names = list(data.rownames)
        d1 = array(data[0])
        d2 = array(data[1])
    d1 = d1.view("float64"); d2 = d2.view("float64")
    z = where(logical_and(d1!=0,d2!=0))[0] #exclude i-th value if either d1[i] or d2[i] is zero
    d1 = d1[z]; d2 = d2[z]
    ratios = log2(d1/d2)
    means = log10(sqrt(d1*d2))
    points = zip(names,ratios,means)
    xmin = min(means); xmax = max(means); ymin = min(ratios); ymax = max(ratios)
    N = len(points); dN = N/bins #points per bin
    rmeans = sort(means)
    intervals = []
    for i in range(bins):
        intervals.append(rmeans[i*dN])
    intervals.append(xmax)
    intervals = array(intervals)
    annotes = []; spline_annotes = []; spline_coords = {}

    points_in = {}; perc = {}
    for b in range(bins):
        points_in[b] = [p for p in points if p[2]>=intervals[b] and p[2]<intervals[b+1]]
        perc[b] = [p[1] for p in points_in[b]]

    fig = plt.figure(figsize=[14,9])
    ax = fig.add_subplot(111)
    fig.subplots_adjust(left=0.08, right=0.98, bottom=0.08, top=0.98)

    ### Points
    ax.plot(means, ratios, ".", color="black")
    
    ### Lines (best fit of percentiles)
    for k in [0.1,1,5,25,50,75,95,99,99.9]:
        h = ones(bins)
        for b in range(bins):
            if points_in[b] != []:
                h[b] = stats.scoreatpercentile(perc[b], k)
            else: h[b] = h[b-1]
            if k==0.1:
                for p in points_in[b]:
                    if p[1]<h[b]: annotes.append(p)
            if k==99.9:
                for p in points_in[b]:
                    if p[1]>h[b]: annotes.append(p)
        if k!=0.1 and k!=99.9:
            x = intervals[:-1]+(intervals[1:]-intervals[:-1])/2.
            spline = UnivariateSpline(x, h, k=deg)
            xs = linspace(xmin, xmax, 10*bins) #to increase spline smoothness
            ys = spline(xs)
            #ax.plot(x, h, "o", color="blue")
            ax.plot(xs, ys, "-", color="blue")
            spline_annotes.append((k,xs[0],ys[0])) #quantile percentages
            spline_coords[k] = zip(xs,ys)

    ### Decoration
    ax.set_xlabel("Log10 of sqrt(x1*x2)")
    ax.set_ylabel("Log2 of x1/x2")
    #ax.set_xlim(xmin-0.2*xmin,xmax+0.2*xmax)
    #ax.set_ylim(ymin-0.2*ymin,ymax+0.2*ymax)
    for l in spline_annotes:
        ax.annotate(str(l[0])+"%", xy=(l[1],l[2]), xytext=(-27,-5), textcoords='offset points')
    if mode == "interactive":
        af = AnnoteFinder( means, ratios, names )
        plt.connect('button_press_event', af)
        plt.draw()
        plt.show()
    if mode == "normal":
        for p in annotes:
            ax.annotate(p[0], xy=(p[2],p[1]) )
        f = fig.savefig("MAplot.png")

    return f, points, spline_coords

class AnnoteFinder:
  """
  Callback for matplotlib to display an annotation when points are clicked on.  The
  point which is closest to the click and within xtol and ytol is identified.

  Register this function like this:

  plot(xdata, ydata)
  af = AnnoteFinder(xdata, ydata, annotes)
  connect('button_press_event', af)
  """

  def __init__(self, xdata, ydata, annotes, axis=None, xtol=None, ytol=None):
    self.data = zip(xdata, ydata, annotes)
    self.xrange = max(xdata) - min(xdata)
    self.yrange = max(ydata) - min(ydata)
    if xtol is None:
      xtol = len(xdata)*(self.xrange/float(len(xdata)))/10
    if ytol is None:
      ytol = len(ydata)*(self.yrange/float(len(ydata)))/10
    self.xtol = xtol
    self.ytol = ytol
    if axis is None:
      self.axis = pylab.gca()
    else:
      self.axis= axis
    self.drawnAnnotations = {}
    self.links = []

  def distance(self, x1, x2, y1, y2):
    """distance between two points"""
    return math.sqrt((x1 - x2)**2 + (y1 - y2)**2)

  def __call__(self, event):
    if event.inaxes:
      clickX = event.xdata
      clickY = event.ydata
      if self.axis is None or self.axis==event.inaxes:
        annotes = []
        for x,y,a in self.data:
          if  clickX-self.xtol < x < clickX+self.xtol and  clickY-self.ytol < y < clickY+self.ytol :
            annotes.append((self.distance(x/self.xrange,clickX/self.xrange,y/self.yrange,clickY/self.yrange),x,y, a) )
        if annotes:
          annotes.sort()
          distance, x, y, annote = annotes[0]
          self.drawAnnote(event.inaxes, x, y, annote)
          for l in self.links:
            l.drawSpecificAnnote(annote)

  def drawAnnote(self, axis, x, y, annote):
    """
    Draw the annotation on the plot
    """
    if (x,y) in self.drawnAnnotations:
      markers = self.drawnAnnotations[(x,y)]
      for m in markers:
        m.set_visible(not m.get_visible())
      self.axis.figure.canvas.draw()
    else:
      t = axis.text(x,y, annote)
      m = axis.scatter([x],[y], marker='d', c='r', zorder=100)
      self.drawnAnnotations[(x,y)] =(t,m)
      self.axis.figure.canvas.draw()

  def drawSpecificAnnote(self, annote):
    annotesToDraw = [(x,y,a) for x,y,a in self.data if a==annote]
    for x,y,a in annotesToDraw:
      self.drawAnnote(self.axis, x, y, a)
