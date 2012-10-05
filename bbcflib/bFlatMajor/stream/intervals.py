import sys
from bbcflib.bFlatMajor import common
from bbcflib.btrack import FeatureStream

# "tracks" and "streams" refer to FeatureStream objects all over here.

def concatenate(trackList, fields=None, remove_duplicates=False):
    """
    Returns one stream containing all features from a list of tracks, ordered by *fields*.

    :param trackList: list of FeatureStream objects.
    :param fields: (list of str) list of fields to keep in the output (at least ['start','end']).
    :param remove_duplicates: (bool) whether to remove items that are identical in several
        of the tracks in *trackList*. [False]
    :rtype: FeatureStream
    """
    def _find_min(feat_tuple):
        """Return the index of the 'smallest' element amongst a tuple of features from
        different tracks. Priority is given to the first field; if the first field items
        are equal amongst several elements, it looks at the second field, a.s.o."""
        nmin = 0
        xmin = feat_tuple[0]
        for n,x in enumerate(feat_tuple[1:]):
            if x[0] == sys.maxint: continue
            for k in range(len(x)):
                if cmp(x[k],xmin[k])<0:
                    xmin = x
                    nmin = n+1
                    break
                if cmp(x[k],xmin[k])>0:
                    break
        return nmin

    def _weave(_t,N):
        """Generator yielding all features represented in a list of tracks *_t*,
        sorted w.r.t the *N* first fields."""
        current = [x.next()[:N] for x in _t] # init
        while 1:
            # Remove duplicates
            if remove_duplicates:
                while not all([current.count(x)==1 for x in current]):
                    for k in range(len(current)):
                        if current.count(current[k]) > 1:
                            current[k] = _t[k].next()[:N]
            n = _find_min(current)
            if current[n][0] == sys.maxint: return
            yield current[n]
            current[n] = _t[n].next()[:N]

    if len(trackList) == 1: return trackList[0]
    if fields is None:
        fields = trackList[0].fields
    fields = [f for f in fields if all(f in t.fields for t in trackList)]
    _of = ['start','end']
    if 'chr' in fields: _of = ['chr']+_of
    if 'name' in fields: _of += ['name']
    _of += [f for f in fields if not(f in _of)]
    tl = [common.reorder(t,_of) for t in trackList]
    tl = [FeatureStream(common.sentinelize(x,(sys.maxint,)*len(x.fields)),x.fields) for x in tl]
    return FeatureStream(_weave(tl,len(_of)),fields=_of)

###############################################################################
@common.ordered
def neighborhood(trackList, before_start=None, after_end=None,
                 after_start=None, before_end=None, on_strand=False):
    """
    Given streams of features and four integers *before_start*, *after_end*,
    *after_start* and *before_end*, this will return one or two features
    for every input feature:

    * Only *before_start* and *after_end* are given::

         (start, end, ...) -> (start-before_start, end+after_end, ...)

    * Only *before_start* and *after_start* are given::

         (start, end, ...) -> (start-before_start, start+after_start, ...)

    * Only *after_end* and *before_end* are given::

         (start, end, ...) -> (end-before_end, end+after_end, ...)

    * If all four parameters are given, a pair of features is generated::

         (start, end, ...) -> (start-before_start, start+after_start, ...)
                              (end-before_end, end+after_end, ...)

    * If the boolean parameter *on_strand* is set to True,
      then `start` and `end` are understood relative to orientation::

         (start, end, -1, ...) -> (start-after_end, start+before_end, -1, ...)
                                  (end-after_start, end+before_start, -1, ...)
         (start, end, +1, ...) -> (start-before_start, start+after_start, +1, ...)
                                  (end-before_end, end+after_end, +1, ...)

    :param trackList: list of FeatureStream objects.
    :param before_start: (int) number of bp before the feature start.
    :param after_end: (int) number of bp after feature end.
    :param after_start: (int) number of bp after the feature start.
    :param before_end: (int) number of bp before the feature end.
    :param on_strand: (bool) True to respect strand orientation. [False]
    :rtype: FeatureStream
    """
    def _generate_single(track,a,b,c,d):
        _buf = []
        for x in track:
            if a:
                if on_strand and x[2]<0:
                    _buf.append((x[0]-after_end,     x[0]+before_end+1) + x[2:])
                    _buf.append((x[1]-after_start-1, x[1]+before_start) + x[2:])
                else:
                    _buf.append((x[0]-before_start, x[0]+after_start+1) + x[2:])
                    _buf.append((x[1]-before_end-1, x[1]+after_end)     + x[2:])
            elif b:
                if on_strand and x[2]<0:
                    _buf.append((x[1]-after_start-1, x[1]+before_start)  + x[2:])
                else:
                    _buf.append((x[0]-before_start,  x[0]+after_start+1) + x[2:])
            elif c:
                if on_strand and x[2]<0:
                    _buf.append((x[0]-after_end,    x[0]+before_end+1) + x[2:])
                else:
                    _buf.append((x[1]-before_end-1, x[1]+after_end)    + x[2:])
            elif d:
                if on_strand and x[2]<0:
                    _buf.append((x[0]-after_end,    x[1]+before_start) + x[2:])
                else:
                    _buf.append((x[0]-before_start, x[1]+after_end)    + x[2:])
            _buf.sort()
            while _buf[0][1] < x[0]: yield _buf.pop(0)
        while _buf: yield _buf.pop(0)

    _fields = ['start','end']
    if on_strand: _fields += ['strand']
    case1 = True
    case2 = True
    case3 = True
    case4 = True
    if before_start is None:
        case1 = case2 = case4 = False
    if after_end is None:
        case1 = case3 = case4 = False
    if after_start is None:
        case1 = case2 = False
    if before_end is None:
        case1 = case3 = False
    if isinstance(trackList,(list,tuple)):
        tl = [common.reorder(t,_fields) for t in trackList]
        return [FeatureStream(_generate_single(t,case1,case2,case3,case4),
                                    fields=t.fields) for t in tl]
    else:
        tl = common.reorder(trackList,_fields)
        return FeatureStream(_generate_single(tl,case1,case2,case3,case4),
                                   fields=tl.fields)

###############################################################################
def _combine(trackList,fn,win_size,aggregate):
    """Generator - see function `combine` below."""
    N = len(trackList)
    fields = trackList[0].fields
    trackList = [common.sentinelize(t, [sys.maxint]*len(fields)) for t in trackList]
    init = [trackList[i].next() for i in range(N)] # the first element of each track
    activity = [False]*N # a vector of boolean values for the N tracks at a given position
    z = [None]*N
    # If there are empty tracks, remove them, and their index from init
    for i in xrange(N-1,-1,-1):
        if init[i][0] == sys.maxint:
            N-=1
            trackList.pop(i)
            init.pop(i)
    if N == 0: return
    available_tracks = range(N-1,-1,-1)
    # Sort starts and ends of all init elements indifferently; record the origin track index.
    current = [(init[i][0],i)+init[i][2:] for i in range(N)] \
            + [(init[i][1],i)+init[i][2:] for i in range(N)]
    current.sort()

    # Init step: set all tracks beginning at the starting point as 'active'
    start = current[0][0]
    while current[0][0] == start:
        i = current[0][1]          # track index
        activity[i] = True         # set this track to 'active'
        z[i] = current.pop(0)[2:]  # z records all meta info

    k=1
    while available_tracks:
        # Load all elements within *win_size* bp in *current*
        to_remove = []
        limit = k * win_size
        for i in available_tracks:
            a = [0,0]
            while a[1] < limit:
                a = trackList[i].next()
                if a[0] == sys.maxint:  # track i is completely read:
                    to_remove.append(i) # remove it from the tracks list
                else:
                    current.append((a[0],i)+a[2:])
                    current.append((a[1],i)+a[2:])
        for i in to_remove:
            available_tracks.remove(i)
        current.sort()
        while current[0][0] >= limit:
            k+=1
            limit = k * win_size
        # Calculate boolean values for this window
        while current and current[0][0] < limit:
            next = current[0][0]
            if fn(activity):
                feat_aggreg = tuple(aggregate.get(f,common.generic_merge)(tuple(zz[n] for zz in z if zz))
                                    for n,f in enumerate(fields[2:]))
                yield (start,next) + feat_aggreg
            while current and current[0][0] == next:
                i = current[0][1]               # track index
                activity[i] = not(activity[i])  # reverse activity
                zi = current.pop(0)[2:]         # record meta info
                z[i] = activity[i] and zi or None
            start = next
        k+=1

@common.ordered
def combine(trackList, fn, win_size=1000,
            aggregate={'strand':common.strand_merge, 'chr':common.no_merge}):
    """
    Applies a custom function to a list of tracks, such as union, intersection,
    etc., and return a single result track. The input streams need to be ordered
    w.r.t chr and start.

    Only fields that are common to all of them are kept. Values for a common field are
    merged by default according to `common.strand_merge`,`common.no_merge` and `common.generic_merge`,
    respectively for strand, chromosome and all others.

    :param trackList: list of FeatureStream objects.
    :param fn: function to apply, such as bbcflib.bFlatMajor.stream.union.
    :param win_size: (int) window size, in bp.
    :param aggregate: (dict) for each field name given as a key, its value is the function
        to apply to the vector containing all trackList's values for this field in order
        to merge them. E.g. ``{'score': lambda x: sum(x)/len(x)}`` will return the average of
        all *trackList*'s scores in the output.
    :rtype: FeatureStream
    """
    fields = ['start','end']
    if len(trackList) < 2: return trackList
    if isinstance(fn,str): fn = eval(fn) # can type combine(...,fn='intersection')
    trackList = [common.cobble(common.reorder(t,fields=fields)) for t in trackList]
    return common.fusion(FeatureStream(_combine(trackList,fn,win_size,aggregate),
                                             fields=trackList[0].fields))

def exclude(x,indexList):
    """Returns True if x[n] is False for all n in *indexList*
    and x[n] is True for at least another n; returns False otherwise."""
    return any([y for n,y in enumerate(x) if not(n in indexList)]) \
       and all([not(y) for n,y in enumerate(x) if n in indexList])

def require(x,indexList):
    """Returns True if x[n] is True for all n in *indexList*
    and x[n] is True for at least another n; returns False otherwise."""
    return any([y for n,y in enumerate(x) if not(n in indexList)]) \
       and all([y for n,y in enumerate(x) if n in indexList])

def disjunction(x,indexList):
    """Returns True if either all True elements of x are in *indexList* or none of them."""
    complementList = [n for n in range(len(x)) if not(n in indexList)]
    return exclude(x,indexList) or exclude(x,complementList)

def intersection(x):
    """Boolean 'AND'."""
    return all(x)

def union(x):
    """Boolean 'OR'."""
    return any(x)


def intersect(trackList, **kw):
    """
    Return all regions covered by an item of every track in *trackList*, returning only fields
    that are common to all tracks in *trackList*. It is a short name for calling `combine` with
    `fn=intersection` and its other optional keyword arguments. Example::

        X1: ___[     chr,A,+,6     ]________[     chr,C,+,3     ]_________
        X2: ________[     chr,B,+,8     ]________[     aaa,C,-,4     ]____
        R:  ________[ chr,A|B,+,14 ]_____________[ chr,C|C,0,7 ]__________
    """
    return combine(trackList, fn=intersection, **kw)

###############################################################################
def segment_features(trackList,nbins=10,upstream=None,downstream=None):
    """
    Split every feature of a track into *nbins* equal segments, and optionally
    adds *upstream* and *downstream* flanks. Flanks are specified as a pair (distance, number_of_bins).
    If the distance is < 1, it is interpreted as a fraction of the feature's length. A new field 'bin'
    giving the index of each fragment produced from a feature is added to the output track. If the
    track shows no field 'strand', all features are considered as being on the forward strand.

    :param trackList: FeatureStream, or list of FeatureStream objects.
    :param nbins: (int) number of bins. [10]
    :param upstream: (tuple (int,float)) upstream flank.
    :param downstream: (tuple (int,float)) downstream flank.
    :rtype: FeatureStream, or list of FeatureStream objects
    """
    def _split_feat(_t):
        starti = _t.fields.index('start')
        endi   = _t.fields.index('end')
        if 'strand' in _t.fields:
            strandi = _t.fields.index('strand')
        else:
            strandi = -1
        uprel = False
        downrel = False
        if upstream is None:
            updist = upbins = 0
        elif upstream[0] > 1: # given in bp
            updist,upbins = upstream
        else:                 # given as a fraction of the feature's length
            uprel = True
            upbins = upstream[1]
        if downstream is None:
            downdist = downbins = 0
        elif downstream[0] > 1: # given in bp
            downdist,downbins = downstream
        else:                   # given as a fraction of the feature's length
            downrel = True
            downbins = downstream[1]
        for x in _t:
            xs = list(x)
            xlen = (xs[endi]-xs[starti])
            if uprel:
                updist = int(.5+upstream[0]*xlen)
            if downrel:
                downdist = int(.5+downstream[0]*xlen)
            if strandi > -1 and xs[strandi] < 0:  # 'strand' field exists and x is on the reverse strand
                allsteps = [x[starti]-downdist*k/downbins for k in range(downbins,0,-1)]\
                           +[x[starti]+xlen*k/nbins for k in range(nbins+1)]\
                           +[x[endi]+updist*(k+1)/upbins for k in range(upbins)]
                start = allsteps[0]
                ntot = len(allsteps)-2
                for n,s in enumerate(allsteps[1:]):
                    xs[starti] = start
                    xs[endi] = s
                    start = s
                    yield tuple(xs)+(ntot-n,)
            else:                                 # either no 'strand' field, or forward strand
                allsteps = [x[starti]-updist*k/upbins for k in range(upbins,0,-1)]\
                           +[x[starti]+xlen*k/nbins for k in range(nbins+1)]\
                           +[x[endi]+downdist*(k+1)/downbins for k in range(downbins)]
                start = allsteps[0]
                for n,s in enumerate(allsteps[1:]):
                    xs[starti] = start
                    xs[endi] = s
                    start = s
                    yield tuple(xs)+(n,)
    if isinstance(trackList, (list,tuple)):
        return [FeatureStream(_split_feat(t), fields=t.fields+['bin'])
                for t in trackList]
    else:
        return FeatureStream(_split_feat(trackList),
                                   fields=trackList.fields+['bin'])
