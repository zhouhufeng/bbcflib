"""
===================================
Submodule: bbcflib.btrack.track_util
===================================

Useful stuff for the track package.
"""

###########################################################################
###########################################################################
## WARNING: The bbcflib.track package is deprecated.                     ##
##          A new project simply called 'track' replaces it.             ##
###########################################################################
###########################################################################

# Built-in modules #
import os, sys, shlex

# Internal modules #
from bbcflib.btrack import formats

###############################################################################
def determine_format(path):
    '''Try to guess the format of a track given its path. Returns a three letter extension'''
    # Try our own sniffing first #
    file_format = guess_file_format(path)
    # Then try the extension #
    if not file_format: file_format = os.path.splitext(path)[1][1:]
    # If still nothing, raise exception #
    if not file_format:
        raise Exception("The format of the path '" + path + "' cannot be determined. Please specify a format or add an extension.")
    # Synonyms #
    known_synonyms = {
        'db': 'sql',
        'bw': 'bigWig',
    }
    # Return the format #
    return known_synonyms.get(file_format, file_format)

#------------------------------------------------------------------------------#
def guess_file_format(path):
    # Check SQLite #
    with open(path, 'r') as track_file:
        if track_file.read(15) == "SQLite format 3": return 'sql'
    # Try to read the track line #
    known_identifiers = {
        'wiggle_0': 'wig',
    }
    with open(path, 'r') as track_file:
        for number, line in enumerate(track_file):
            line = line.strip("\n").lstrip()
            if number > 100:                break
            if line.startswith("track "):
                try:
                    id = dict([p.split('=',1) for p in shlex.split(line[6:])])['type']
                except ValueError:
                    id = ''
                return known_identifiers.get(id, id)

#------------------------------------------------------------------------------#
def import_implementation(format):
    '''
    Try to import the implementation of a given format.
    It will look in 'bbcflib.formats' module the given 'format'
    exist as a file.
    e.g.: for 'my_file.bed' it will look for 'bed.py'
    '''
    if not hasattr(sys.modules[__package__].formats, format):
        try:
            __import__(__package__ + '.formats.' + format)
        except ImportError :
            raise Exception('Format %s not supported' % format)
    return sys.modules[__package__ + '.formats.' + format]

#------------------------------------------------------------------------------#
def join_read_queries(track, selections, fields):
    '''Join read results when selection is a list'''
    def _add_chromsome_prefix(sel, data):
        if type(sel) == str: chrom = (sel,)
        else:                chrom = (sel['chr'],)
        for f in data: yield chrom + f
    for sel in selections:
        for f in _add_chromsome_prefix(sel, track.read(sel, fields)): yield f

#------------------------------------------------------------------------------#
def make_cond_from_sel(selection):
    '''Make an SQL condition string from a selection dictionary'''
    query = ""
    # Case start #
    if "start" in selection:
        query += "end > " + str(selection['start'])
        if selection.get('inclusion') == 'strict': query += " and start >= " + str(selection['start'])
    # Case end #
    if "end" in selection:
        if query: query += " and "
        query += "start < " + str(selection['end'])
        if selection.get('inclusion') == 'strict': query += " and end <= " + str(selection['end'])
    # Case strand #
    if "strand" in selection:
        if query: query += " and "
        query += 'strand == ' + str(selection['strand'])
    # Case score #
    if "score" in selection:
        if not isinstance(selection['score'], tuple): raise Exception("Score intervals must be tuples of size 2")
        if query: query += " and "
        query += 'score >= ' + str(selection['score'][0]) + ' and score <= ' + str(selection['score'][1])
    return query

#-----------------------------------#
# This code was written by the BBCF #
# http://bbcf.epfl.ch/              #
# webmaster.bbcf@epfl.ch            #
#-----------------------------------#