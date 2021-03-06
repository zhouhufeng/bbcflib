Track manipulations
===================

Here is a short tutorial showing how to manipulate streams of data with the Python library
**gfminer** from the **bbcflib** package.

What is it useful for?
----------------------

The **track** library from the **bbcflib** package reads track-like files and returns iterators ("streams")
over the data (see **track**'s :doc:`tutorial <tutorial_track>` and :doc:`documentation <bbcflib_track>`).
Usually, one wants to modify this data through a sequence of manipulations before writing it back.
**gfminer** provides a collection of useful functions that take streams as input and perform
common manipulations such as concatenate, intersect or reorder.

Before starting
---------------

This tutorial assumes that you already went through
:doc:`track's tutorial <tutorial_track>`,
and thus a "stream" in this context is a short name for a :func:`bbcflib.track.FeatureStream` object.

A ``FeatureStream`` is an iterator, thus **a stream can be read only once**.
To read the data a second time, one must recreate the stream (read the track again).

Glossary
--------

* **Stream**: a :func:`FeatureStream <bbcflib.track.FeatureStream>` object.
* **Feature**: a genomic region, usually an entity such as a gene, exon, etc.
* **Feature track/stream**: a sequence of genomic regions, usually describing annotation
  (e.g. position of all genes).
* **Score track/stream**: a sequence of intervals associated to a score, each genomic
  position in the interval having the same score (e.g. read coverage).

How do I use it?
----------------

First, create a stream from scratch or from a track file::

    >>> from bbcflib.track import FeatureStream
    >>> s = FeatureStream([('chr1',12,13),('chr1',24,28)],fields=['chr','start','end'])

    # or

    >>> from bbcflib.track import track
    >>> t = track("myfile.bed")
    >>> s = t.read(fields=['chr','start','end'])

Then import the function(s) that you need and give your stream as input::

    >>> from bbcflib.gfminer.common import duplicate
    >>> s1 = duplicate(s,'chr','newfield') # copies the 'chr' field to a new one

    >>> s1
    <bbcflib.track.FeatureStream object at 0x534248907>
    >>> s1.next()
    ('chr1',12,13,'chr1')
    >>> s1.fields
    ['chr','start','end','chr']

Of course, one can chain functions as long as they return streams::

    >>> from bbcflib.gfminer.common import apply
    >>> s2 = apply(s1,'newfield', lambda x:"aaa") # rename all 'newfield' entries to 'aaa'
    >>> s3 = apply(s2,'end', lambda x:x+12)       # add 12 to all 'end' entries
    >>> s3.next()
    ('chr1',24,40,'aaa')

    # or equivalently:

    >>> s3 = apply(apply(duplicate(s,...) ,...) ,...)

Finally, write the result to a new file using **track**::

    >>> from bbcflib.track import track
    >>> t = track("newfile.bed", fields=s1.fields)
    >>> t.write(s1)
    >>> t.close()

For many of **gfminer**'s functions,

1. The track must be sorted w.r.t. chromosome, start, end (in this priority order).
   This can be done with a shell ``sort``, but we propose to use the inner
   :func:`bbcflib.gfminer.common.sorted_stream` on the stream itself for this purpose
   (will not modify the original file).

2. The function must be applied chromosome by chromosome. Typically::

    from bbcflib.gfminer.common import fusion
    from bbcflib.track import track
    t = track("byfile.bed", chrmeta='mm9')
    out = track("newfile.bed")
    for chr in t.chrmeta:
        s = t.read(chr)
        s1 = fusion(s)
        out.write(s1)

    # Running ``fusion`` on the whole genome would paste together
    # regions from different chromosomes.

Both concern every function that has to compare two regions' coordinates.
In general, we advise to always loop on the chomosomes list.

How do I find the function I need?
----------------------------------

**gfminer**'s functions are classified in four submodules:

* **common**: low-level, usual manipulations, usually called implicitly inside of other functions.
* **stream**: functions that return streams.
* **numeric**: functions that return vectors of matrices (*numpy* arrays).
* **figure**: functions that create plots (using a binding to R).

Here are brief descriptions of the main functions (subject to changes):

gfminer.common functions:
############################

``from bbcflib.gfminer.common import *``

* :func:`copy <bbcflib.gfminer.common.copy>`:
  return n independant copies of the input stream.
* :func:`select <bbcflib.gfminer.common.select>`:
  keep only the specified fields.
* :func:`reorder <bbcflib.gfminer.common.reorder>`:
  change the fields' order.
* :func:`apply <bbcflib.gfminer.common.apply>`:
  apply a custom function to all entries of the specified field(s).
* :func:`duplicate <bbcflib.gfminer.common.duplicate>`:
  copy one of the fields and its entries to a new one.
* :func:`concat_fields <bbcflib.gfminer.common.concat_fields>`:
  concatenate two fields and their respective entries.
* :func:`split_field <bbcflib.gfminer.common.split_field>`:
  when possible, split a field and its entries into two distinct ones.
* :func:`map_chromosomes <bbcflib.gfminer.common.map_chromosomes>`:
  translate chromosome names to GenRep standard (e.g. 'chr1').
* :func:`score_threshold <bbcflib.gfminer.common.score_threshold>`:
  filter scores with respect to a threshold.
* :func:`unroll <bbcflib.gfminer.common.unroll>`:
  return one score per genomic position.
* :func:`sorted_stream <bbcflib.gfminer.common.sorted_stream>`:
  sort the stream, by default w.r.t chr, start and end.
* :func:`shuffled <bbcflib.gfminer.common.shuffled>`:
  return a stream of randomly located features similar to the original stream.
* :func:`fusion <bbcflib.gfminer.common.fusion>`:
  fuse every two overlapping regions A,B into a single one A|B.
* :func:`cobble <bbcflib.gfminer.common.cobble>`:
  break every two overlapping regions A,B into three: A - A|B - B.

gfminer.stream functions:
############################

``from bbcflib.gfminer.stream import *``

* :func:`getNearestFeature <bbcflib.gfminer.stream.annotate.getNearestFeature>`:
  find the nearest gene to each of the input's features.
* :func:`concatenate <bbcflib.gfminer.stream.intervals.concatenate>`:
  make a single stream from the union of several ones.
* :func:`selection <bbcflib.gfminer.stream.intervals.selection>`:
  filter elements of a stream w.r.t. some given criteria.
* :func:`overlap <bbcflib.gfminer.stream.intervals.overlap>`:
  keep only items overlapping at least one element of a filter track.
* :func:`neighborhood <bbcflib.gfminer.stream.intervals.neighborhood>`:
  enlarge each of the input's regions.
* :func:`intersect <bbcflib.gfminer.stream.intervals.intersect>`:
  return the intersection of several streams.
* :func:`merge_scores <bbcflib.gfminer.stream.scores.merge_scores>`:
  return a stream with per-base average (or sum) of several signal tracks.
* :func:`filter_scores <bbcflib.gfminer.stream.scores.filter_scores>`:
  keep only scores belonging to a given set of regions.
* :func:`score_by_feature <bbcflib.gfminer.stream.scores.score_by_feature>`:
  attribute to each given region the sum or average of (independantly) given scores that span the region.
* :func:`window_smoothing <bbcflib.gfminer.stream.scores.window_smoothing>`:
  apply to the scores a smoothing filter along the sequence.
* :func:`normalize <bbcflib.gfminer.stream.scores.normalize>`:
  normalize the scores between several signal tracks.

gfminer.numeric functions:
#############################

``from bbcflib.gfminer.numeric import *``

* :func:`score_array <bbcflib.gfminer.numeric.signal.score_array>`:
  return a vector of scores, one for each unique name in the stream.
* :func:`correlation <bbcflib.gfminer.numeric.signal.correlation>`:
  calculate the auto-correlation.
* :func:`feature_matrix <bbcflib.gfminer.numeric.regions.feature_matrix>`:
  return an array with names as rows and scores as columns, one column for each input score stream.
* :func:`summed_feature_matrix <bbcflib.gfminer.numeric.regions.summed_feature_matrix>`:
  return an array with for each input score stream, the average score over all features.

gfminer.figure functions:
############################

``from bbcflib.gfminer.figure import *``

* :func:`scatterplot <bbcflib.gfminer.figure.rplots.scatterplot>`:
  scatter plot (2-d points).
* :func:`lineplot <bbcflib.gfminer.figure.rplots.lineplot>`:
  same, but points are bounded by lines.
* :func:`boxplot <bbcflib.gfminer.figure.rplots.boxplot>`:
  box plot (quantile plot).
* :func:`heatmap <bbcflib.gfminer.figure.rplots.heatmap>`:
  heat map (2-d colored matrix).
* :func:`pairs <bbcflib.gfminer.figure.rplots.pairs>`:
  a scatter plot of each pair of variables one against the other.

Common errors
-------------

* **StopIteration**: The stream is empty, but one tries to read its next element.
* **IndexError**: Most of the time, this is due to an incoherence with the number of fields,
  or a required field that was not found.
* **TypeError**: Common fields, such as 'chr','start','end','frame','strand','score', have
  specific types (resp. str,int,int,int,int,float). Ensure that if you give such a name to a field,
  its entries have the right type.
* **ValueError**: Can have a lot of different causes, but often due to conversion issues
  (see **TypeError**). Ensure that numeric entries are not surrounded by quotes.

Advanced features
-----------------

* Fields names:

  One can change a stream fields name by just resetting its ``fields`` attribute::

    >>> s = FeatureStream([('chr1',12,14)], fields=['chr','start','end'])
    >>> s.fields = ['chromosome','initial','final']
    >>> s.fields
    ['chromosome','initial','final']
    >>> s.next() # the content is unchanged
    ('chr1',12,14)

  Streams yield standard tuples, so one gets individual entries by fetching the index
  of the field of interest::

    >>> s = FeatureStream([('chr1',12,14)], fields=['chr','start','end'])
    >>> x = s.next()
    >>> start_idx = s.fields.index('start')
    >>> start = x[start_idx]
    >>> start
    12

  The order of stream fields should not matter in most cases, since all functions listed
  here use field names to get the information.

* The function :func:`combine <bbcflib.gfminer.stream.intervals.combine>` permits
  to apply any custom boolean operation to a list of tracks.
  :func:`intersect <bbcflib.gfminer.stream.intervals.intersect>` is just an example
  using the AND boolean operator. Here is a more complex one:

  Let A,B,C be three streams, one could ask for
  ((A OR B) AND C). At each position in the chromosome, a stream gives 1 if one of
  its elements covers the position, 0 else. Say A and B give 1, and C gives 0.
  Then ((1 OR 1) AND 0) is 0, so the output stream will not cover this position.

* Build your own function:

  Most of the functions listed here have roughly the following structure::

    def my_custom_function(stream):
        def _generate(S):
            for x in S:
                ... # transform x
                yield x
        return FeatureStream(_generate(stream), fields=stream.fields)

More documentation
------------------

* For more details on how each individual function works,
  look at the :doc:`developer documentation <bbcflib_gfminer>`.
* Numerous tests are available with the source code (`bbcflib/bbcflib/tests/test_gfminer.py`)
  that give for each function at least one simple example of usage.


