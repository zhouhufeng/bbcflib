"""
====================================
Submodule: bbcflib.btrack.formats.sql
====================================

Implementation of the SQL format.
"""

###########################################################################
###########################################################################
## WARNING: The bbcflib.track package is deprecated.                     ##
##          A new project simply called 'track' replaces it.             ##
###########################################################################
###########################################################################

# Built-in modules #
import re, sqlite3

# Internal modules #
from bbcflib.btrack import Track
from bbcflib.btrack.track_util import join_read_queries, make_cond_from_sel
from bbcflib.btrack.extras.sql import TrackExtras
from bbcflib.btrack.common import natural_sort, int_to_roman, roman_to_int

################################################################################
class TrackFormat(Track, TrackExtras):
    special_tables = ['attributes', 'chrNames', 'types']

    def __init__(self, path, format=None, name=None, chrmeta=None, datatype=None, readonly=False, empty=False):
        # Set the path #
        self.path = path
        # Prepare the connection #
        self.connection = sqlite3.connect(self.path)
        self.cursor = self.connection.cursor()
        self.modified = False
        # Get the track meta data #
        self.attributes = self.attributes_read()
        self.attributes.modified = False
        # Get the chromosome meta data #
        if chrmeta: self.chrmeta = chrmeta
        else:
            self.chrmeta = self.chrmeta_read()
            self.chrmeta.modified = False
        # Check for missing attributes #
        if not datatype and not self.datatype: self.datatype = 'qualitative'
        # Check for present attributes #
        if name: self.name = name
        if datatype:
            if not self.datatype: self.datatype = datatype
            if self.datatype != datatype: raise Exception("You cannot change the datatype of the track '" + self.path + "'")
        # Set chromosome list #
        self.chrs_from_tables

    def unload(self, datatype=None, value=None, traceback=None):
        if self.attributes.modified: self.attributes_write()
        if self.chrmeta.modified: self.chrmeta_write()
        self.make_missing_tables()
        self.make_missing_indexes()
        self.connection.commit()
        self.cursor.close()
        self.connection.close()

    def commit(self):
        self.connection.commit()

    def make_missing_indexes(self):
        if self.readonly: return
        try:
            for chrom in self.chrs_from_tables:
                self.cursor.execute(    "create index IF NOT EXISTS '" + chrom + "_range_idx' on '" + chrom + "' (start,end)")
                if 'score' in self.get_fields_of_table(chrom):
                    self.cursor.execute("create index IF NOT EXISTS '" + chrom + "_score_idx' on '" + chrom + "' (score)")
                if 'name' in self.get_fields_of_table(chrom):
                    self.cursor.execute("create index IF NOT EXISTS '" + chrom + "_name_idx' on '" +  chrom + "' (name)")
        except sqlite3.OperationalError as err:
            raise Exception("The index creation on the database '" + self.path + "' failed with error: " + str(err))

    def make_missing_tables(self):
        if self.readonly: return
        for chrom in set(self.chrs_from_names) - set(self.chrs_from_tables):
            columns = ','.join([field + ' ' + Track.field_types.get(field, 'text') for field in self.fields or getattr(Track, self.datatype + '_fields')])
            self.cursor.execute('create table "' + chrom + '" (' + columns + ')')

    #--------------------------------------------------------------------------#
    @property
    def fields(self):
        if self.chrs_from_tables: return self.get_fields_of_table(self.chrs_from_tables[0])
        else:                     return []

    @property
    def all_tables(self):
        self.cursor.execute("select name from sqlite_master where type='table'")
        return [x[0].encode('ascii') for x in self.cursor.fetchall()]

    @property
    def chrs_from_names(self):
        if 'chrNames' not in self.all_tables: return []
        self.cursor.execute("select name from chrNames")
        return [x[0].encode('ascii') for x in self.cursor.fetchall()]

    @property
    def chrs_from_tables(self):
        self.all_chrs = [x for x in self.all_tables if x not in self.special_tables and not x.endswith('_idx')]
        self.all_chrs.sort(key=natural_sort)
        return self.all_chrs

    def get_fields_of_table(self, table):
        return [x[1] for x in self.cursor.execute('pragma table_info("' + table + '")').fetchall()]

    #--------------------------------------------------------------------------#
    def attributes_read(self):
        if not 'attributes' in self.all_tables: return {}
        self.cursor.execute("select key, value from attributes")
        return dict(self.cursor.fetchall())

    def attributes_write(self):
        if self.readonly: return
        self.cursor.execute('drop table IF EXISTS attributes')
        if self.attributes:
            self.cursor.execute('create table attributes (key text, value text)')
            for k in self.attributes.keys(): self.cursor.execute('insert into attributes (key,value) values (?,?)', (k, self.attributes[k]))

    def chrmeta_read(self):
        if not 'chrNames' in self.all_tables: return {}
        self.cursor.execute("pragma table_info(chrNames)")
        column_names = [x[1] for x in self.cursor.fetchall()]
        all_rows = self.cursor.execute("select * from chrNames").fetchall()
        return column_names, all_rows

    def chrmeta_write(self):
        if self.readonly: return
        self.cursor.execute('drop table IF EXISTS chrNames')
        if self.chrmeta:
            self.cursor.execute('create table chrNames (name text, length integer)')
            for r in self.chrmeta.rows: self.cursor.execute('insert into chrNames (' + ','.join(r.keys()) + ') values (' + ','.join(['?' for x in r.keys()])+')', tuple(r.values()))

    @property
    def chrmeta(self):
        return self._chrmeta

    @chrmeta.setter
    def chrmeta(self, value):
        self._chrmeta(value)

    @property
    def attributes(self):
        return self._attributes

    @attributes.setter
    def attributes(self, value):
        self._attributes(value)

    @property
    def datatype(self):
        # Next line is a hack to remove a new datatype introduced by GDV - remove at a later date #
        if self.attributes.get('datatype') == 'QUALITATIVE_EXTENDED': return 'qualitative'
        # End hack #
        return self.attributes.get('datatype', '').lower()

    @datatype.setter
    def datatype(self, value):
        if value not in ['quantitative', 'qualitative']:
            raise Exception("The datatype you are trying to use is invalid: '" + str(value) + "'.")
        self.attributes['datatype'] = value

    @property
    def name(self):
        return self.attributes.get('name', 'Unnamed')

    @name.setter
    def name(self, value):
        self.attributes['name'] = value

    #--------------------------------------------------------------------------#
    def read(self, selection=None, fields=None, order='start,end', cursor=False):
        # Default selection #
        if not selection: selection = self.chrs_from_tables
        # Case list of things #
        if isinstance(selection, (list, tuple)):
            return join_read_queries(self, selection, fields)
        # Case chromosome name #
        elif isinstance(selection, basestring): chrom = selection
        # Case selection dictionary #
        elif isinstance(selection, dict): chrom = selection['chr']
        # Other cases #
        else: raise TypeError, 'The following selection parameter: "' + selection + '" was not understood'
        # Empty chromosome case #
        if chrom not in self.chrs_from_tables: return ()
        # Default columns #
        columns = fields and fields[:] or self.get_fields_of_table(chrom)
        # Next lines are a hack to add an empty column needed by GDV - remove at a later date #
        if not fields or 'attributes' not in fields:
            try: columns.remove('attributes')
            except ValueError: pass
        # End hack #
        # Make the query #
        sql_request = "select " + ','.join(columns) + " from '" + chrom + "'"
        if isinstance(selection, dict): sql_request += " where " + make_cond_from_sel(selection)
        order_by = 'order by ' + order
        # Return the results #
        if cursor: cur = self.connection.cursor()
        else:      cur = self.cursor
        return cur.execute(sql_request + ' ' + order_by)

    def write(self, chrom, data, fields=None):
        self.modified = True
        if self.readonly: return
        # Default fields #
        if self.datatype == 'quantitative': fields = Track.quantitative_fields
        if not fields:                      fields = Track.qualitative_fields
        # Maybe create the table #
        if chrom not in self.chrs_from_tables:
            columns = ','.join([field + ' ' + Track.field_types.get(field, 'text') for field in fields])
            # Next line is a hack to add an empty column needed by GDV - remove at a later date #
            if self.datatype == 'qualitative' and 'attributes' not in fields: columns += ',attributes text'
            # End hack #
            self.cursor.execute('create table "' + chrom + '" (' + columns + ')')
        # Execute the insertion
        sql_command = 'insert into "' + chrom + '" (' + ','.join(fields) + ') values (' + ','.join(['?' for x in range(len(fields))])+')'
        try:
            self.cursor.executemany(sql_command, data)
        except (sqlite3.OperationalError, sqlite3.ProgrammingError) as err:
            raise Exception("The command '" + sql_command + "' on the database '" + self.path + "' failed with error: '" + str(err) + "'" + \
                '\n    ' + 'The bindings: ' + str(fields) + \
                '\n    ' + 'You gave: ' + str(data))

    def remove(self, chrom=None):
        self.modified = True
        if self.readonly: return
        if not chrom:
            chrom = self.chrs_from_tables
        if isinstance(chrom, list):
            for ch in chrom: self.remove(ch)
        else:
            self.cursor.execute("DROP table '" + chrom + "'")
            if chrom in self.chrmeta: self.chrmeta.pop(chrom)

    def rename(self, previous_name, new_name):
        self.modified = True
        if self.readonly: return
        if previous_name not in self.chrs_from_tables: raise Exception("The chromosome '" + previous_name + "' doesn't exist.")
        self.cursor.execute("ALTER TABLE '" + previous_name + "' RENAME TO '" + new_name + "'")
        self.cursor.execute("drop index IF EXISTS '" + previous_name + "_range_idx'")
        self.cursor.execute("drop index IF EXISTS '" + previous_name + "_score_idx'")
        self.cursor.execute("drop index IF EXISTS '" + previous_name + "_name_idx'")
        if previous_name in self.chrmeta:
            self.chrmeta[new_name] = self.chrmeta[previous_name]
            self.chrmeta.pop(previous_name)
        self.chrs_from_tables

    def count(self, selection=None):
        # Default selection #
        if not selection:
            selection = self.chrs_from_tables
        # Case several chromosome #
        if isinstance(selection, list) or isinstance(selection, tuple):
            return sum([self.count(s) for s in selection])
        # Case chromosome name #
        elif isinstance(selection, basestring):
            if selection not in self.chrs_from_tables: return 0
            sql_request = "select COUNT(*) from '" + selection + "'"
        # Case span dictionary #
        elif isinstance(selection, dict):
            chrom = selection['chr']
            if chrom not in self.chrs_from_tables: return 0
            sql_request = "select COUNT(*) from '" + chrom + "' where " + make_cond_from_sel(selection)
        # Other cases #
        else: raise TypeError, 'The following selection parameter: "' + selection + '" was not understood'
        # Return the results #
        return self.cursor.execute(sql_request).fetchone()[0]

    def ucsc_to_ensembl(self):
        for chrom in self.chrs_from_tables: self.cursor.execute("update '" + chrom + "' set start=start+1")

    def ensembl_to_ucsc(self):
        for chrom in self.chrs_from_tables: self.cursor.execute("update '" + chrom + "' set start=start-1")

    def score_vector(self, chrom):
        # Conditions #
        if 'score' not in self.fields:
            def add_ones(X):
                for x in X: yield x + (1.0,)
            data = add_ones(self.read(chrom, ['start','end']))
        else:
            data = self.read(chrom, ['start','end','score'])
        # Initialization #
        last_end = 0
        x = (-1,0)
        # Core loop #
        for x in data:
            for i in xrange(last_end, x[0]): yield 0.0
            for i in xrange(x[0],     x[1]): yield x[2]
            last_end = x[1]
        # End piece #
        if self.chrmeta.get(chrom):
            for i in xrange(x[1], self.chrmeta[chrom]['length']): yield 0.0

    def roman_to_integer(self, names=None):
        names = names or {'chrM':'chrQ', '2micron':'chrR'}
        def convert(chrom):
            if chrom in names: return names[chrom]
            match = re.search('([a-zA-Z]*?)([IVX]+)$', chrom)
            return match.group(1) + str(roman_to_int(match.group(2)))
        for chrom in self: self.rename(chrom, convert(chrom))

    def integer_to_roman(self, names=None):
        names = names or {'chrQ':'chrM', 'chrR':'2micron'}
        def convert(chrom):
            if chrom in names: return names[chrom]
            match = re.search('([a-zA-Z]*)([0-9]+)$', chrom)
            return match.group(1) + int_to_roman(int(match.group(2)))
        for chrom in self: self.rename(chrom, convert(chrom))

    #--------------------------------------------------------------------------#
    @staticmethod
    def create(path):
        connection = sqlite3.connect(path)
        cursor = connection.cursor()
        connection.commit()
        cursor.close()
        connection.close()

#-----------------------------------#
# This code was written by the BBCF #
# http://bbcf.epfl.ch/              #
# webmaster.bbcf@epfl.ch            #
#-----------------------------------#