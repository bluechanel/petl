"""
TODO doc me

"""


import csv
import os
import zlib
import cPickle as pickle
import sqlite3


from petl.util import data, header, fieldnames, asdict


class Uncacheable(Exception):
    
    def __init__(self, nested=None):
        self.nested = nested


def crc32sum(filename):
    """
    Compute the CRC32 checksum of the file at the given location. Returns
    the checksum as an integer, use hex(result) to view as hexadecimal.
    
    """
    
    checksum = None
    with open(filename, 'rb') as f:
        while True:
            data = f.read(8192)
            if not data:
                break
            if checksum is None:
                checksum = zlib.crc32(data) & 0xffffffffL # deal with signed integer
            else:
                checksum = zlib.crc32(data, checksum) & 0xffffffffL # deal with signed integer
    return checksum


def adler32sum(filename):
    """
    Compute the Adler 32 checksum of the file at the given location. Returns
    the checksum as an integer, use hex(result) to view as hexadecimal.
    
    """
    
    checksum = None
    with open(filename, 'rb') as f:
        while True:
            data = f.read(8192)
            if not data:
                break
            if checksum is None:
                checksum = zlib.adler32(data) & 0xffffffffL # deal with signed integer
            else:
                checksum = zlib.adler32(data, checksum) & 0xffffffffL # deal with signed integer
    return checksum


def statsum(filename):
    """
    Compute a crude checksum of the file by hashing the file's absolute path
    name, the file size, and the file's time of last modification. N.B., on
    some systems this will give a 1s resolution, i.e., any changes to a file
    within the same second that preserve the file size will *not* change the
    result.
    
    """
    
    return hash((os.path.abspath(filename), 
                 os.path.getsize(filename), 
                 os.path.getmtime(filename)))


defaultsumfun = statsum
"""
Default checksum function used when generating cachetags for file-backed tables.

To change the default globally, e.g.::

    >>> import petl.io
    >>> petl.io.defaultsumfun = petl.io.adler32sum
    
"""
        

def fromcsv(filename, checksumfun=None, **kwargs):
    """
    Wrapper for the standard :func:`csv.reader` function. Returns a table providing
    access to the data in the given delimited file. The `filename` argument is the
    path of the delimited file, all other keyword arguments are passed to 
    :func:`csv.reader`. E.g.::

        >>> import csv
        >>> # set up a CSV file to demonstrate with
        ... with open('test.csv', 'wb') as f:
        ...     writer = csv.writer(f, delimiter='\\t')
        ...     writer.writerow(['foo', 'bar'])
        ...     writer.writerow(['a', 1])
        ...     writer.writerow(['b', 2])
        ...     writer.writerow(['c', 2])
        ...
        >>> # now demonstrate the use of petl.fromcsv
        ... from petl import fromcsv, look
        >>> testcsv = fromcsv('test.csv', delimiter='\\t')
        >>> look(testcsv)
        +-------+-------+
        | 'foo' | 'bar' |
        +=======+=======+
        | 'a'   | '1'   |
        +-------+-------+
        | 'b'   | '2'   |
        +-------+-------+
        | 'c'   | '2'   |
        +-------+-------+

    Note that all data values are strings, and any intended numeric values will
    need to be converted, see also :func:`convert`.
    
    The returned table object implements the `cachetag()` method. If the 
    `checksumfun` argument is not given, the default checksum function (whatever
    `petl.io.defaultsumfun` is currently set to) will be used to calculate 
    cachetag values.
    
    """

    return CSVView(filename, checksumfun=checksumfun, **kwargs)


class CSVView(object):
    
    def __init__(self, filename, checksumfun=None, **kwargs):
        self.filename = filename
        self.checksumfun = checksumfun
        self.kwargs = kwargs
        
    def __iter__(self):
        with open(self.filename, 'rb') as file:
            reader = csv.reader(file, **self.kwargs)
            for row in reader:
                yield tuple(row)
                
    def cachetag(self):
        p = self.filename
        if os.path.isfile(p):
            sumfun = self.checksumfun if self.checksumfun is not None else defaultsumfun
            checksum = sumfun(p)
            return hash((checksum, tuple(self.kwargs.items()))) 
        else:
            raise Uncacheable
                
    
def frompickle(filename, checksumfun=None):
    """
    Returns a table providing access to the data pickled in the given file. The 
    rows in the table should have been pickled to the file one at a time. E.g.::

        >>> import pickle
        >>> # set up a file to demonstrate with
        ... with open('test.dat', 'wb') as f:
        ...     pickle.dump(['foo', 'bar'], f)
        ...     pickle.dump(['a', 1], f)
        ...     pickle.dump(['b', 2], f)
        ...     pickle.dump(['c', 2.5], f)
        ...
        >>> # now demonstrate the use of petl.frompickle
        ... from petl import frompickle, look
        >>> testdat = frompickle('test.dat')
        >>> look(testdat)
        +-------+-------+
        | 'foo' | 'bar' |
        +=======+=======+
        | 'a'   | 1     |
        +-------+-------+
        | 'b'   | 2     |
        +-------+-------+
        | 'c'   | 2.5   |
        +-------+-------+

    The returned table object implements the `cachetag()` method. If the 
    `checksumfun` argument is not given, the default checksum function (whatever
    `petl.io.defaultsumfun` is currently set to) will be used to calculate 
    cachetag values.
    
    """
    
    return PickleView(filename, checksumfun=checksumfun)
    
    
class PickleView(object):

    def __init__(self, filename, checksumfun=None):
        self.filename = filename
        self.checksumfun = checksumfun
        
    def __iter__(self):
        with open(self.filename, 'rb') as file:
            try:
                while True:
                    yield tuple(pickle.load(file))
            except EOFError:
                pass
                
    def cachetag(self):
        p = self.filename
        if os.path.isfile(p):
            sumfun = self.checksumfun if self.checksumfun is not None else defaultsumfun
            checksum = sumfun(p)
            return checksum
        else:
            raise Uncacheable
    

def fromsqlite3(filename, query, checksumfun=None):
    """
    Provides access to data from an :mod:`sqlite3` database file via a given query. E.g.::

        >>> import sqlite3
        >>> from petl import look, fromsqlite3    
        >>> # initial data
        >>> data = [['a', 1],
        ...         ['b', 2],
        ...         ['c', 2.0]]
        >>> connection = sqlite3.connect('test.db')
        >>> c = connection.cursor()
        >>> c.execute('create table foobar (foo, bar)')
        <sqlite3.Cursor object at 0x2240b90>
        >>> for row in data:
        ...     c.execute('insert into foobar values (?, ?)', row)
        ... 
        <sqlite3.Cursor object at 0x2240b90>
        <sqlite3.Cursor object at 0x2240b90>
        <sqlite3.Cursor object at 0x2240b90>
        >>> connection.commit()
        >>> c.close()
        >>> # demonstrate the petl.fromsqlite3 function
        ... foobar = fromsqlite3('test.db', 'select * from foobar')
        >>> look(foobar)    
        +-------+-------+
        | 'foo' | 'bar' |
        +=======+=======+
        | u'a'  | 1     |
        +-------+-------+
        | u'b'  | 2     |
        +-------+-------+
        | u'c'  | 2.0   |
        +-------+-------+

    The returned table object implements the `cachetag()` method. If the 
    `checksumfun` argument is not given, the default checksum function (whatever
    `petl.io.defaultsumfun` is currently set to) will be used to calculate 
    cachetag values.
    
    """
    
    return Sqlite3View(filename, query, checksumfun)


class Sqlite3View(object):

    def __init__(self, filename, query, checksumfun=None):
        self.filename = filename
        self.query = query
        self.checksumfun = checksumfun
        
    def __iter__(self):
        connection = sqlite3.connect(self.filename)
        cursor = connection.execute(self.query)
        fields = [d[0] for d in cursor.description]
        yield tuple(fields)
        for result in cursor:
            yield tuple(result)
        connection.close()

    def cachetag(self):
        p = self.filename
        if os.path.isfile(p):
            sumfun = self.checksumfun if self.checksumfun is not None else defaultsumfun
            checksum = sumfun(p)
            return hash((checksum, self.query))
        else:
            raise Uncacheable
                
    
def fromdb(connection, query):
    """
    Provides access to data from any DB-API 2.0 connection via a given query. 
    E.g., using `sqlite3`::

        >>> import sqlite3
        >>> from petl import look, fromdb
        >>> connection = sqlite3.connect('test.db')
        >>> table = fromdb(connection, 'select * from foobar')
        >>> look(table)
        
    E.g., using `psycopg2` (assuming you've installed it first)::
    
        >>> import psycopg2
        >>> from petl import look, fromdb
        >>> connection = psycopg2.connect("dbname=test user=postgres")
        >>> table = fromdb(connection, 'select * from test')
        >>> look(table)
        
    E.g., using `MySQLdb` (assuming you've installed it first)::
    
        >>> import MySQLdb
        >>> from petl import look, fromdb
        >>> connection = MySQLdb.connect(passwd="moonpie", db="thangs")
        >>> table = fromdb(connection, 'select * from test')
        >>> look(table)
        
    The returned table object does not implement the `cachetag()` method.
        
    """
    
    return DbView(connection, query)


class DbView(object):

    def __init__(self, connection, query):
        self.connection = connection
        self.query = query
        
    def __iter__(self):
        cursor = self.connection.execute(self.query)
        fields = [d[0] for d in cursor.description]
        yield tuple(fields)
        for result in cursor:
            yield tuple(result)
            
            
def fromtext(filename, header=['lines'], strip=None, checksumfun=None):
    """
    Construct a table from lines in the given text file. E.g.::

        >>> # example data
        ... with open('test.txt', 'w') as f:
        ...     f.write('a\\t1\\n')
        ...     f.write('b\\t2\\n')
        ...     f.write('c\\t3\\n')
        ... 
        >>> from petl import fromtext, look
        >>> table1 = fromtext('test.txt')
        >>> look(table1)
        +--------------+
        | 'lines'      |
        +==============+
        | 'a\\t1'     |
        +--------------+
        | 'b\\t2'     |
        +--------------+
        | 'c\\t3'     |
        +--------------+

    The :func:`fromtext` function provides a starting point for custom handling of 
    text files. E.g., using :func:`capture`::
    
        >>> from petl import capture
        >>> table2 = capture(table1, 'lines', '(.*)\\\\t(.*)$', ['foo', 'bar'])
        >>> look(table2)
        +-------+-------+
        | 'foo' | 'bar' |
        +=======+=======+
        | 'a'   | '1'   |
        +-------+-------+
        | 'b'   | '2'   |
        +-------+-------+
        | 'c'   | '3'   |
        +-------+-------+

    .. versionchanged:: 0.4
    
    The strip() function is called on each line, which by default will remove 
    leading and trailing whitespace, including the end-of-line character - use 
    the `strip` keyword argument to specify alternative characters to strip.    
    
    """

    return TextView(filename, header, strip=strip, checksumfun=checksumfun)


class TextView(object):
    
    def __init__(self, filename, header=['lines'], strip=None, checksumfun=None):
        self.filename = filename
        self.header = header
        self.strip = strip
        self.checksumfun = checksumfun
        
    def __iter__(self):
        with open(self.filename, 'rU') as file:
            if self.header is not None:
                yield tuple(self.header)
            s = self.strip
            for line in file:
                yield (line.strip(s),)
                
    def cachetag(self):
        p = self.filename
        if os.path.isfile(p):
            sumfun = self.checksumfun if self.checksumfun is not None else defaultsumfun
            checksum = sumfun(p)
            return checksum
        else:
            raise Uncacheable

    
def tocsv(table, filename, **kwargs):
    """
    Write the table to a CSV file. E.g.::

        >>> from petl import tocsv
        >>> table = [['foo', 'bar'],
        ...          ['a', 1],
        ...          ['b', 2],
        ...          ['c', 2]]
        >>> tocsv(table, 'test.csv', delimiter='\\t')
        >>> # look what it did
        ... from petl import look, fromcsv
        >>> look(fromcsv('test.csv', delimiter='\\t'))
        +-------+-------+
        | 'foo' | 'bar' |
        +=======+=======+
        | 'a'   | '1'   |
        +-------+-------+
        | 'b'   | '2'   |
        +-------+-------+
        | 'c'   | '2'   |
        +-------+-------+

    Note that if a file already exists at the given location, it will be overwritten.
    
    """
    
    with open(filename, 'wb') as f:
        writer = csv.writer(f, **kwargs)
        for row in table:
            writer.writerow(row)


def appendcsv(table, filename, **kwargs):
    """
    Append data rows to an existing CSV file. E.g.::

        >>> # look at an existing CSV file
        ... from petl import look, fromcsv
        >>> testcsv = fromcsv('test.csv', delimiter='\\t')
        >>> look(testcsv)
        +-------+-------+
        | 'foo' | 'bar' |
        +=======+=======+
        | 'a'   | '1'   |
        +-------+-------+
        | 'b'   | '2'   |
        +-------+-------+
        | 'c'   | '2'   |
        +-------+-------+
        
        >>> # append some data
        ... from petl import appendcsv 
        >>> table = [['foo', 'bar'],
        ...          ['d', 7],
        ...          ['e', 42],
        ...          ['f', 12]]
        >>> appendcsv(table, 'test.csv', delimiter='\\t')
        >>> # look what it did
        ... look(testcsv)
        +-------+-------+
        | 'foo' | 'bar' |
        +=======+=======+
        | 'a'   | '1'   |
        +-------+-------+
        | 'b'   | '2'   |
        +-------+-------+
        | 'c'   | '2'   |
        +-------+-------+
        | 'd'   | '7'   |
        +-------+-------+
        | 'e'   | '42'  |
        +-------+-------+
        | 'f'   | '12'  |
        +-------+-------+

    Note that no attempt is made to check that the fields or row lengths are 
    consistent with the existing data, the data rows from the table are simply
    appended to the file. See also the :func:`cat` function.
    
    """
    
    with open(filename, 'ab') as f:
        writer = csv.writer(f, **kwargs)
        for row in data(table):
            writer.writerow(row)


def topickle(table, filename, protocol=-1):
    """
    Write the table to a pickle file. E.g.::

        >>> from petl import topickle
        >>> table = [['foo', 'bar'],
        ...          ['a', 1],
        ...          ['b', 2],
        ...          ['c', 2]]
        >>> topickle(table, 'test.dat')
        >>> # look what it did
        ... from petl import look, frompickle
        >>> look(frompickle('test.dat'))
        +-------+-------+
        | 'foo' | 'bar' |
        +=======+=======+
        | 'a'   | 1     |
        +-------+-------+
        | 'b'   | 2     |
        +-------+-------+
        | 'c'   | 2     |
        +-------+-------+

    Note that if a file already exists at the given location, it will be overwritten.

    The pickle file format preserves type information, i.e., reading and writing 
    is round-trippable.
    
    """
    
    with open(filename, 'wb') as file:
        for row in table:
            pickle.dump(row, file, protocol)
    

def appendpickle(table, filename, protocol=-1):
    """
    Append data to an existing pickle file. E.g.::

        >>> # inspect an existing pickle file
        ... from petl import look, frompickle
        >>> testdat = frompickle('test.dat')
        >>> look(testdat)
        +-------+-------+
        | 'foo' | 'bar' |
        +=======+=======+
        | 'a'   | 1     |
        +-------+-------+
        | 'b'   | 2     |
        +-------+-------+
        | 'c'   | 2     |
        +-------+-------+
        
        >>> # append some data
        ... from petl import appendpickle
        >>> table = [['foo', 'bar'],
        ...          ['d', 7],
        ...          ['e', 42],
        ...          ['f', 12]]
        >>> appendpickle(table, 'test.dat')
        >>> # look what it did
        ... look(testdat)
        +-------+-------+
        | 'foo' | 'bar' |
        +=======+=======+
        | 'a'   | 1     |
        +-------+-------+
        | 'b'   | 2     |
        +-------+-------+
        | 'c'   | 2     |
        +-------+-------+
        | 'd'   | 7     |
        +-------+-------+
        | 'e'   | 42    |
        +-------+-------+
        | 'f'   | 12    |
        +-------+-------+

    Note that no attempt is made to check that the fields or row lengths are 
    consistent with the existing data, the data rows from the table are simply
    appended to the file. See also the :func:`cat` function.
    
    """
    
    with open(filename, 'ab') as file:
        for row in data(table):
            pickle.dump(row, file, protocol)
    

def tosqlite3(table, filename, tablename, create=True):
    """
    Load data into a table in an :mod:`sqlite3` database. Note that if
    the database table exists, it will be truncated, i.e., all
    existing rows will be deleted prior to inserting the new
    data. E.g.::

        >>> table = [['foo', 'bar'],
        ...          ['a', 1],
        ...          ['b', 2],
        ...          ['c', 2]]
        >>> from petl import tosqlite3
        >>> # by default, if the table does not already exist, it will be created
        ... tosqlite3(table, 'test.db', 'foobar')
        >>> # look what it did
        ... from petl import look, fromsqlite3
        >>> look(fromsqlite3('test.db', 'select * from foobar'))
        +-------+-------+
        | 'foo' | 'bar' |
        +=======+=======+
        | u'a'  | 1     |
        +-------+-------+
        | u'b'  | 2     |
        +-------+-------+
        | u'c'  | 2     |
        +-------+-------+

    """
    
    tablename = _quote(tablename)
    names = [_quote(n) for n in fieldnames(table)]

    conn = sqlite3.connect(filename)
    if create:
        conn.execute('create table if not exists %s (%s)' % (tablename, ', '.join(names)))
    conn.execute('delete from %s' % tablename)
    placeholders = ', '.join(['?'] * len(names))
    _insert(conn, tablename, placeholders, table)
    conn.commit()
    
    
def appendsqlite3(table, filename, tablename):
    """
    Load data into an existing table in an :mod:`sqlite3`
    database. Note that the database table will be appended, i.e., the
    new data will be inserted into the table, and any existing rows
    will remain. E.g.::
    
        >>> moredata = [['foo', 'bar'],
        ...             ['d', 7],
        ...             ['e', 9],
        ...             ['f', 1]]
        >>> from petl import appendsqlite3
        >>> appendsqlite3(moredata, 'test.db', 'foobar') 
        >>> # look what it did
        ... from petl import look, fromsqlite3
        >>> look(fromsqlite3('test.db', 'select * from foobar'))
        +-------+-------+
        | 'foo' | 'bar' |
        +=======+=======+
        | u'a'  | 1     |
        +-------+-------+
        | u'b'  | 2     |
        +-------+-------+
        | u'c'  | 2     |
        +-------+-------+
        | u'd'  | 7     |
        +-------+-------+
        | u'e'  | 9     |
        +-------+-------+
        | u'f'  | 1     |
        +-------+-------+

    """

    # sanitise table name
    tablename = _quote(tablename)

    conn = sqlite3.connect(filename)
    flds = header(table) # just need to know how many fields there are
    placeholders = ', '.join(['?'] * len(flds))
    _insert(conn, tablename, placeholders, table)
    conn.commit()
    
    
    
def todb(table, connection, tablename, commit=True):
    """
    Load data into an existing database table via a DB-API 2.0
    connection. Note that the database table will be truncated, i.e.,
    all existing rows will be deleted prior to inserting the new data.
    
    E.g., using :mod:`sqlite3`::
    
        >>> import sqlite3
        >>> connection = sqlite3.connect('test.db')
        >>> table = [['foo', 'bar'],
        ...          ['a', 1],
        ...          ['b', 2],
        ...          ['c', 2]]
        >>> from petl import todb
        >>> # assuming table "foobar" already exists in the database
        ... todb(table, connection, 'foobar')    
        
    E.g., using :mod:`psycopg2`::

        >>> import psycopg2 
        >>> connection = psycopg2.connect("dbname=test user=postgres")
        >>> table = [['foo', 'bar'],
        ...          ['a', 1],
        ...          ['b', 2],
        ...          ['c', 2]]
        >>> from petl import todb
        >>> # assuming table "foobar" already exists in the database
        ... todb(table, connection, 'foobar')    
        
    E.g., using :mod:`MySQLdb`::

        >>> import MySQLdb
        >>> connection = MySQLdb.connect(passwd="moonpie", db="thangs")
        >>> table = [['foo', 'bar'],
        ...          ['a', 1],
        ...          ['b', 2],
        ...          ['c', 2]]
        >>> from petl import todb
        >>> # assuming table "foobar" already exists in the database
        ... todb(table, connection, 'foobar')    
        
    """

    # sanitise table and field names
    tablename = _quote(tablename)
    names = [_quote(n) for n in fieldnames(table)]
    placeholders = _placeholders(connection, names)

    # truncate the table
    c = connection.cursor()
    c.execute('delete from %s' % tablename)
    
    # insert some data
    _insert(c, tablename, placeholders, table)

    # finish up
    if commit:
        connection.commit()
    c.close()
    
    
def appenddb(table, connection, tablename, commit=True):
    """
    Load data into an existing database table via a DB-API 2.0
    connection. Note that the database table will be appended, i.e.,
    the new data will be inserted into the table, and any existing
    rows will remain.
    
    E.g., using :mod:`sqlite3`::
    
        >>> import sqlite3
        >>> connection = sqlite3.connect('test.db')
        >>> table = [['foo', 'bar'],
        ...          ['a', 1],
        ...          ['b', 2],
        ...          ['c', 2]]
        >>> from petl import appenddb
        >>> # assuming table "foobar" already exists in the database
        ... appenddb(table, connection, 'foobar')    
        
    E.g., using :mod:`psycopg2`::

        >>> import psycopg2 
        >>> connection = psycopg2.connect("dbname=test user=postgres")
        >>> table = [['foo', 'bar'],
        ...          ['a', 1],
        ...          ['b', 2],
        ...          ['c', 2]]
        >>> from petl import appenddb
        >>> # assuming table "foobar" already exists in the database
        ... appenddb(table, connection, 'foobar')    
        
    E.g., using :mod:`MySQLdb`::

        >>> import MySQLdb
        >>> connection = MySQLdb.connect(passwd="moonpie", db="thangs")
        >>> table = [['foo', 'bar'],
        ...          ['a', 1],
        ...          ['b', 2],
        ...          ['c', 2]]
        >>> from petl import appenddb
        >>> # assuming table "foobar" already exists in the database
        ... appenddb(table, connection, 'foobar')    
        
    """

    # sanitise table and field names
    tablename = _quote(tablename)
    names = [_quote(n) for n in fieldnames(table)]
    placeholders = _placeholders(connection, names)
    
    # insert some data
    c = connection.cursor()
    _insert(c, tablename, placeholders, table)

    # finish up
    if commit:
        connection.commit()
    c.close()


def _quote(s):
    # crude way to sanitise table and field names
    return '"%s"' % s.replace('"', '')


def _insert(cursor, tablename, placeholders, table):    
    insertquery = 'insert into %s values (%s)' % (tablename, placeholders)
    for row in data(table):
        cursor.execute(insertquery, row)

    
def _placeholders(connection, names):    
    # discover the paramstyle
    mod = __import__(connection.__class__.__module__)
    if mod.paramstyle == 'qmark':
        placeholders = ', '.join(['?'] * len(names))
    elif mod.paramstyle in ('format', 'pyformat'):
        # TODO test this!
        placeholders = ', '.join(['%s'] * len(names))
    elif mod.paramstyle == 'numeric':
        # TODO test this!
        placeholders = ', '.join([':' + str(i + 1) for i in range(len(names))])
    else:
        raise Exception('TODO')
    return placeholders


def totext(table, filename, template, prologue=None, epilogue=None):
    """
    Write the table to a text file. E.g.::

        >>> from petl import totext    
        >>> table = [['foo', 'bar'],
        ...          ['a', 1],
        ...          ['b', 2],
        ...          ['c', 2]]
        >>> prologue = \"\"\"{| class="wikitable"
        ... |-
        ... ! foo
        ... ! bar
        ... \"\"\"
        >>> template = \"\"\"|-
        ... | {foo}
        ... | {bar}
        ... \"\"\"
        >>> epilogue = "|}"
        >>> totext(table, 'test.txt', template, prologue, epilogue)
        >>> 
        >>> # see what we did
        ... with open('test.txt') as f:
        ...     print f.read()
        ...     
        {| class="wikitable"
        |-
        ! foo
        ! bar
        |-
        | a
        | 1
        |-
        | b
        | 2
        |-
        | c
        | 2
        |}
        
    The `template` will be used to format each row via `str.format <http://docs.python.org/library/stdtypes.html#str.format>`_.
    """
    
    with open(filename, 'w') as f:
        if prologue is not None:
            f.write(prologue)
        it = iter(table)
        flds = it.next()
        for row in it:
            rec = asdict(flds, row)
            s = template.format(**rec)
            f.write(s)
        if epilogue is not None:
            f.write(epilogue)
            
    
def appendtext(table, filename, template, prologue=None, epilogue=None):
    """
    As :func:`totext` but the file is opened in append mode.
    
    """

    with open(filename, 'a') as f:
        if prologue is not None:
            f.write(prologue)
        it = iter(table)
        flds = it.next()
        for row in it:
            rec = asdict(flds, row)
            s = template.format(**rec)
            f.write(s)
        if epilogue is not None:
            f.write(epilogue)
            

