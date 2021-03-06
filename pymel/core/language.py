"""
Functions and classes related to scripting, including `MelGlobals` and `Mel`
"""
import sys, os, inspect
import shelve
from getpass import getuser as _getuser
import system
import bsddb.db as _db

import maya.mel as _mm
import maya.cmds as _mc

import pymel.util as util
import pymel.internal as _internal
import pymel.internal.pmcmds as cmds
import pymel.internal.factories as _factories
import pymel.api as _api
import datatypes
import pymel.versions as versions

_logger = _internal.getLogger(__name__)


#--------------------------
# Mel <---> Python Glue
#--------------------------

MELTYPES = ['string', 'string[]', 'int', 'int[]', 'float', 'float[]', 'vector', 'vector[]']

def isValidMelType( typStr ):
    """:rtype: bool"""
    return typStr in MELTYPES

def _flatten(iterables):
    for it in iterables:
        if util.isIterable(it):
            for element in it:
                yield element
        else:
            yield it

def pythonToMel(arg):
    """
    convert a python object to a string representing an equivalent value in mel

    iterables are flattened.

    mapping types like dictionaries have their key value pairs flattened:
        { key1 : val1, key2 : val2 }  -- >  ( key1, val1, key2, val2 )

    """
    if util.isNumeric(arg):
        return str(arg)
    if isinstance(arg, datatypes.Vector):
        return '<<%f,%f,%f>>' % ( arg[0], arg[1], arg[2] )
    if util.isIterable(arg):
        if util.isMapping(arg):
            arg = list(_flatten(arg.iteritems()))
        else:
            arg = list(_flatten(arg))
        forceString = False
        for each in arg:
            if not util.isNumeric(each):
                forceString = True
                break

        if forceString:
            newargs = [ '"%s"' % x for x in arg ]
        else:
            newargs = [ str(x) for x in arg ]

        return '{%s}' % ','.join( newargs )

    # in order for PyNodes to get wrapped in quotes we have to treat special cases first,
    # we cannot simply test if arg is an instance of basestring because PyNodes are not
    return '"%s"' % cmds.encodeString(str(arg))


def getMelType( pyObj, exactOnly=True, allowBool=False, allowMatrix=False ):
    """
    return the name of the closest MEL type equivalent for the given python object.
    MEL has no true boolean or matrix types, but it often reserves special treatment for them in other ways.
    To control the handling of these types, use `allowBool` and `allowMatrix`.
    For python iterables, the first element in the array is used to determine the type. for empty lists, 'string[]' is
    returned.

        >>> from pymel.all import *
        >>> getMelType( 1 )
        'int'
        >>> p = SCENE.persp
        >>> getMelType( p.translate.get() )
        'vector'
        >>> getMelType( datatypes.Matrix )
        'int[]'
        >>> getMelType( datatypes.Matrix, allowMatrix=True )
        'matrix'
        >>> getMelType( True )
        'int'
        >>> getMelType( True, allowBool=True)
        'bool'
        >>> # make a dummy class
        >>> class MyClass(object): pass
        >>> getMelType( MyClass ) # returns None
        >>> getMelType( MyClass, exactOnly=False )
        'MyClass'

    :Parameters:
        pyObj
            can be either a class or an instance.
        exactOnly : bool
            If True and no suitable MEL analog can be found, the function will return None.
            If False, types which do not have an exact mel analog will return the python type name as a string
        allowBool : bool
            if True and a bool type is passed, 'bool' will be returned. otherwise 'int'.
        allowMatrix : bool
            if True and a `Matrix` type is passed, 'matrix' will be returned. otherwise 'int[]'.

    :rtype: `str`


    """

    if inspect.isclass(pyObj):

        if issubclass( pyObj, basestring ) : return 'string'
        elif allowBool and issubclass( pyObj, bool ) : return 'bool'
        elif issubclass( pyObj, int ) : return 'int'
        elif issubclass( pyObj, float ) : return 'float'
        elif issubclass( pyObj, datatypes.VectorN ) : return 'vector'
        elif issubclass( pyObj, datatypes.MatrixN ) :
            if allowMatrix:
                return 'matrix'
            else:
                return 'int[]'

        elif not exactOnly:
            return pyObj.__name__

    else:
        if isinstance( pyObj, datatypes.VectorN ) : return 'vector'
        elif isinstance( pyObj, datatypes.MatrixN ) :
            if allowMatrix:
                return 'matrix'
            else:
                return 'int[]'
        elif util.isIterable( pyObj ):
            try:
                return getMelType( pyObj[0], exactOnly=True ) + '[]'
            except IndexError:
                # TODO : raise warning
                return 'string[]'
            except:
                return
        if isinstance( pyObj, basestring ) : return 'string'
        elif allowBool and isinstance( pyObj, bool ) : return 'bool'
        elif isinstance( pyObj, int ) : return 'int'
        elif isinstance( pyObj, float ) : return 'float'


        elif not exactOnly:
            return type(pyObj).__name__


# TODO : convert array variables to a semi-read-only list ( no append or extend, += is ok ):
# using append or extend will not update the mel variable
class MelGlobals( dict ):
    """ A dictionary-like class for getting and setting global variables between mel and python.
    an instance of the class is created by default in the pymel namespace as melGlobals.

    to retrieve existing global variables, just use the name as a key

    >>> melGlobals['gResourceFileList'] #doctest: +ELLIPSIS
    [u'defaultRunTimeCommands.res.mel', u'localizedPanelLabel.res.mel', ...]
    >>> # works with or without $
    >>> melGlobals['gFilterUIDefaultAttributeFilterList']  #doctest: +ELLIPSIS
    [u'DefaultHiddenAttributesFilter', u'animCurveFilter', ..., u'publishedFilter']

    creating new variables requires the use of the initVar function to specify the type

    >>> melGlobals.initVar( 'string', 'gMyStrVar' )
    '$gMyStrVar'
    >>> melGlobals['gMyStrVar'] = 'fooey'

    The variable will now be accessible within MEL as a global string.
    """
    #__metaclass__ = util.Singleton
    melTypeToPythonType = {
        'string'    : str,
        'int'       : int,
        'float'     : float,
        'vector'    : datatypes.Vector
        }

#    class MelGlobalArray1( tuple ):
#        def __new__(cls, type, variable, *args, **kwargs ):
#
#            self = tuple.__new__( cls, *args, **kwargs )
#
#            decl_name = variable
#            if type.endswith('[]'):
#                type = type[:-2]
#                decl_name += '[]'
#
#            self._setItemCmd = "global %s %s; %s" % ( type, decl_name, variable )
#            self._setItemCmd += '[%s]=%s;'
#            return self
#
#        def setItem(self, index, value ):
#            _mm.eval(self._setItemCmd % (index, value) )

    class MelGlobalArray( util.defaultlist ):
        #__metaclass__ = util.metaStatic
        def __init__(self, type, variable, *args, **kwargs ):

            decl_name = variable
            if type.endswith('[]'):
                type = type[:-2]
                decl_name += '[]'

            pyType = MelGlobals.melTypeToPythonType[ type ]
            util.defaultlist.__init__( self, pyType, *args, **kwargs )


            self._setItemCmd = "global %s %s; %s" % ( type, decl_name, variable )
            self._setItemCmd += '[%s]=%s;'


        def setItem(self, index, value ):
            _mm.eval(self._setItemCmd % (index, value) )

        # prevent these from
        def append(self, val): raise AttributeError
        def __setitem__(self, item, val): raise AttributeError
        def extend(self, val): raise AttributeError



    typeMap = {}
    VALID_TYPES = MELTYPES


    def __getitem__(self, variable ):
        return self.__class__.get( variable )

    def __setitem__(self, variable, value):
        return self.__class__.set( variable, value )

    @classmethod
    def _formatVariable(cls, variable):
        # TODO : add validity check
        if not variable.startswith( '$'):
            variable = '$' + variable
        return variable

    @classmethod
    def getType(cls, variable):
        variable = cls._formatVariable(variable)
        info = mel.whatIs( variable ).split()
        if len(info)==2 and info[1] == 'variable':
            return info[0]
        raise TypeError, "Cannot determine type for this variable. Use melGlobals.initVar first."

    @classmethod
    def initVar( cls, type, variable ):
        if type not in MELTYPES:
            raise TypeError, "type must be a valid mel type: %s" % ', '.join( [ "'%s'" % x for x in MELTYPES ] )
        variable = cls._formatVariable(variable)
        MelGlobals.typeMap[variable] = type
        return variable

    @classmethod
    def get( cls, variable, type=None  ):
        """get a MEL global variable.  If the type is not specified, the mel ``whatIs`` command will be used
        to determine it."""

        variable = cls._formatVariable(variable)
        if type is None:
            try:
                type = MelGlobals.typeMap[variable]
            except KeyError:
                try:
                    type = cls.getType(variable)
                except TypeError:
                    raise KeyError, variable

        variable = cls.initVar(type, variable)

        ret_type = type
        decl_name = variable

        if type.endswith('[]'):
            array=True
            type = type[:-2]
            proc_name = 'pymel_get_global_' + type + 'Array'
            if not decl_name.endswith('[]'):
                decl_name += '[]'
        else:
            array=False
            proc_name = 'pymel_get_global_' + type

        cmd = "global proc %s %s() { global %s %s; return %s; } %s();" % (ret_type, proc_name, type, decl_name, variable, proc_name )
        #print cmd
        res = _mm.eval( cmd  )
        if array:
            return MelGlobals.MelGlobalArray(ret_type, variable, res)
        else:
            return MelGlobals.melTypeToPythonType[type](res)

    @classmethod
    def set( cls, variable, value, type=None ):
        """set a mel global variable"""
        variable = cls._formatVariable(variable)
        if type is None:
            try:
                type = MelGlobals.typeMap[variable]
            except KeyError:
                type = cls.getType(variable)

        variable = cls.initVar(type, variable)
        decl_name = variable
        if type.endswith('[]'):
            type = type[:-2]
            decl_name += '[]'

        cmd = "global %s %s; %s=%s;" % ( type, decl_name, variable, pythonToMel(value) )
        #print cmd
        _mm.eval( cmd  )

    @classmethod
    def keys(cls):
        """list all global variables"""
        return mel.env()

melGlobals = MelGlobals()

# for backward compatibility
def getMelGlobal(type, variable) :
    return melGlobals.get(variable, type)
def setMelGlobal(type, variable, value) :
    return melGlobals.set(variable, value, type)


class Catch(object):
    """Reproduces the behavior of the mel command of the same name. if writing pymel scripts from scratch, you should
        use the try/except structure. This command is provided for python scripts generated by py2mel.  stores the
        result of the function in catch.result.

        >>> if not catch( lambda: myFunc( "somearg" ) ):
        ...    result = catch.result
        ...    print "succeeded:", result

        """
    #__metaclass__ = util.Singleton
    result = None
    success = None
    def __call__(self, func ):
        try:
            Catch.result = func()
            Catch.success = True
            return 0
        except:
            Catch.success = False
            return 1

    def reset(self):
        Catch.result = None
        Catch.success = None

catch = Catch()


class OptionVarList(tuple):

    def __new__(cls, val, key):
        self = tuple.__new__(cls, val)
        return self

    def __init__(self, val, key):
        tuple.__init__(self, val)
        self.key = key


    def appendVar( self, val ):
        """ values appended to the OptionVarList with this method will be added to the Maya optionVar at the key denoted by self.key.
        """

        if isinstance( val, basestring):
            return cmds.optionVar( stringValueAppend=[self.key,val] )
        if isinstance( val, int):
            return cmds.optionVar( intValueAppend=[self.key,val] )
        if isinstance( val, float):
            return cmds.optionVar( floatValueAppend=[self.key,val] )
        raise TypeError, 'unsupported datatype: strings, ints, floats and their subclasses are supported'

    append = appendVar

class OptionVarDict(object):
    """
    A singleton dictionary-like class for accessing and modifying optionVars.

        >>> from pymel.all import *
        >>> optionVar['test'] = 'dooder'
        >>> optionVar['test']
        u'dooder'

        >>> if 'numbers' not in env.optionVars:
        ...     optionVar['numbers'] = [1,24,7]
        >>> optionVar['numbers'].appendVar( 9 )
        >>> numArray = optionVar.pop('numbers')
        >>> print numArray
        [1, 24, 7, 9]
        >>> optionVar.has_key('numbers') # previous pop removed the key
        False
    """
    #__metaclass__ = util.Singleton
    def __call__(self, *args, **kwargs):
        return cmds.optionVar(*args, **kwargs)

    def __contains__(self, key):
        return self.has_key(key)

    def has_key(self, key):
        return bool( cmds.optionVar( exists=key ) )

    def __getitem__(self,key):
        if not self.has_key(key):
            raise KeyError, key
        val = cmds.optionVar( q=key )
        if isinstance(val, list):
            val = OptionVarList( val, key )
        return val

    def get(self, key, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def __setitem__(self,key,val):
        if isinstance( val, basestring):
            return cmds.optionVar( stringValue=[key,val] )
        if isinstance( val, (int, bool)):
            return cmds.optionVar( intValue=[key,int(val)] )
        if isinstance( val, float):
            return cmds.optionVar( floatValue=[key,val] )
        if isinstance( val, (list,tuple) ):
            if len(val) == 0:
                return cmds.optionVar( clearArray=key )
            listType = type(val[0])
            if issubclass( listType , basestring):
                flag = 'stringValue'
            elif issubclass( listType , int):
                flag = 'intValue'
            elif issubclass( listType , float):
                flag  = 'floatValue'
            else:
                raise TypeError, ('%r is unsupported; Only strings, ints, float, lists, and their subclasses are supported' % listType)

            cmds.optionVar(**{flag:[key,val[0]]}) # force to this datatype
            flag += "Append"
            for elem in val[1:]:
                if not isinstance( elem, listType):
                    raise TypeError, 'all elements in list must be of the same datatype'
                cmds.optionVar( **{flag:[key,elem]} )

    def keys(self):
        return cmds.optionVar( list=True )

    def values(self):
        return [self[key] for key in self.keys()]

    def pop(self, key):
        val = cmds.optionVar( q=key )
        cmds.optionVar( remove=key )
        return val

    def __delitem__(self,key):
        self.pop(key)

    def iterkeys(self):
        for key in self.keys():
            yield key
    __iter__ = iterkeys

    def itervalues(self):
        for key in self.keys():
            yield self[key]

    def iteritems(self):
        for key in self.keys():
            yield key, self[key]


class OptionVarShelve( OptionVarDict ):
    """
    OptionVarShelve extends OptionVarDict to support python datatypes.
    If a value type is MEL-supported, it will be stored in Maya userPrefs and accessible by MEL.
    Otherwise, it will be stored as a pickled python object.

    With exceptions set to True, behavior will be like standard dictionary.
    Otherwise it will behave like OptionVarDict, returning 0 if key does not exist.

        >>> from pymel.all import *
        >>> optionVar['test'] = ['a',10,3.14]
        >>> optionVar['test']
        ['a',10,3.14]
        >>> optionVar.has_key('test')
        True
        >>> optionVar.has_key('test',language='mel')
        False
        >>> optionVar.has_key('test',language='python')
        True
        >>> optionVar['test'] = ['a','b','c']
        >>> optionVar.has_key('test',language='mel')
        True
        >>> optionVar.has_key('test',language='python')
        False
        >>> optionVar['test']
        ['a','b','c']

    """

    __metaclass__ = util.Singleton

    def __init__(self, exceptions=True ):
        self._exceptions = exceptions

        self._optionVars = OptionVarDict()

        bin_path = os.path.join( _internal.getMayaAppDir(), versions.installName(), "prefs", "prefs.bin")

        try:
            self._shelve = shelve.open(bin_path)
        except _db.DBPermissionsError:
            _logger.warn( 'Permission Error accessing "prefs.bin". Python-only options vars will not be saved.' )
            self._shelve = {}

        _id = _api.MEventMessage.addEventCallback( 'quitApplication', self._close )


    def _close(self, *args):
        self._shelve.close()


    def has_key(self, key, language=''):
        """Extra language argument for checking where option is stored."""

        if language not in ['','mel','python']:
            raise TypeError, "language keyword expects 'mel', or 'python'. got '%s'" % language

        if language == '':
            if self._optionVars.has_key(key):
                return True
            elif self._shelve.has_key(key):
                return True
        elif language == "mel":
            if self._optionVars.has_key(key):
                return True
        elif language == "python":
            if self._shelve.has_key(key):
                return True

        return False


    def __getitem__(self, key):
        if self._optionVars.has_key(key):
            return self._optionVars.__getitem__(key)
        elif self._shelve.has_key(key):
            return self._shelve.__getitem__(key)
        else:
            if self._exceptions:
                raise KeyError, '(%s,)' % str(key)
            else:
                return 0


    def __setitem__(self, key, val):
        # making sure that the optionVar is removed from shelve in the event
        # that the new value is MEL-supported
        if self._shelve.has_key(key):
            self._shelve.pop(key)

        try:
            self._optionVars.__setitem__(key,val)
        except TypeError:
            # if the option exists but the new value type is not MEL-supported,
            # be sure it is removed from MEL prefs before adding it to shelve.
            self._optionVars.pop(key)
            self._shelve.__setitem__(key,val)


    def keys(self):
        return self._optionVars.keys() + self._shelve.keys()


    def pop(self, key):
        if self._optionVars.has_key(key):
            return self._optionVars.pop(key)
        elif self._exceptions:
            return self._shelve.pop(key)
        else:
            return self._shelve.pop(key,0)


melOptionVar = OptionVarDict()
optionVar = OptionVarShelve()


class Env(object):
    """ A Singleton class to represent Maya current optionVars and settings """
    #__metaclass__ = util.Singleton

    optionVars = OptionVarDict()
    #grid = Grid()
    #playbackOptions = PlaybackOptions()

    # TODO : create a wrapper for os.environ which allows direct appending and popping of individual env entries (i.e. make ':' transparent)
    envVars = os.environ

    def setConstructionHistory( self, state ):
        cmds.constructionHistory( tgl=state )
    def getConstructionHistory(self):
        return cmds.constructionHistory( q=True, tgl=True )
    def sceneName(self):
        return system.Path(cmds.file( q=1, sn=1))

    def setUpAxis( self, axis, rotateView=False ):
        """This flag specifies the axis as the world up direction. The valid axis are either 'y' or 'z'."""
        cmds.upAxis( axis=axis, rotateView=rotateView )

    def getUpAxis(self):
        """This flag gets the axis set as the world up direction. The valid axis are either 'y' or 'z'."""
        return cmds.upAxis( q=True, axis=True )

    def user(self):
        return _getuser()
    def host(self):
        return _gethostname()

    def getTime( self ):
        return cmds.currentTime( q=1 )
    def setTime( self, val ):
        cmds.currentTime( val )
    time = property( getTime, setTime )

    def getMinTime( self ):
        return cmds.playbackOptions( q=1, minTime=1 )
    def setMinTime( self, val ):
        cmds.playbackOptions( minTime=val )
    minTime = property( getMinTime, setMinTime )

    def getMaxTime( self ):
        return cmds.playbackOptions( q=1, maxTime=1 )
    def setMaxTime( self, val ):
        cmds.playbackOptions( maxTime=val )
    maxTime = property( getMaxTime, setMaxTime )

env = Env()

#--------------------------
# Maya.mel Wrapper
#--------------------------

class MelError(RuntimeError):
    """Generic MEL error"""
    pass

class MelConversionError(MelError,TypeError):
    """MEL cannot process a conversion or cast between data types"""
    pass

class MelUnknownProcedureError(MelError,NameError):
    """The called MEL procedure does not exist or has not been sourced"""
    pass

class MelArgumentError(MelError,TypeError):
    """The arguments passed to the MEL script are incorrect"""
    pass

class MelSyntaxError(MelError,SyntaxError):
    """The MEL script has a syntactical error"""
    pass

class Mel(object):
    """This class is a convenience for calling mel scripts from python, but if you are like me, you'll quickly find that it
    is a necessity. It allows mel scripts to be called as if they were python functions: it automatically formats python
    arguments into a command string which is executed via maya.mel.eval.  An instance of this class is already created for you
    when importing pymel and is called `mel`.



    default:
        >>> import maya.mel as mel
        >>> # create the proc
        >>> mel.eval( 'global proc myScript( string $stringArg, float $floatArray[] ){}')
        >>> # run the script
        >>> mel.eval( 'myScript("firstArg", {1.0, 2.0, 3.0})')

    pymel:
        >>> from pymel.all import *
        >>> # create the proc
        >>> mel.eval( 'global proc myScript( string $stringArg, float $floatArray[] ){}')
        >>> # run the script
        >>> mel.myScript("firstArg", [1.0, 2.0, 3.0])

    The above is a very simplistic example. The advantages of pymel.mel over maya.mel.eval are more readily
    apparent when we want to pass a python object to our mel procedure:

    default:
        >>> import maya.cmds as cmds
        >>> node = "lambert1"
        >>> color = cmds.getAttr( node + ".color" )[0]
        >>> mel.eval('myScript("%s",{%f,%f,%f})' % (cmds.nodeType(node), color[0], color[1], color[2])   )

    pymel:
        >>> from pymel.all import *
        >>> node = PyNode("lambert1")
        >>> mel.myScript( node.type(), node.color.get() )

    In this you can see how `pymel.core.mel` allows you to pass any python object directly to your mel script as if
    it were a python function, with no need for formatting arguments.  The resulting code is much more readable.

    Another advantage of this class over maya.mel.eval is its handling of mel errors.  If a mel procedure fails to
    execute, you will get the specific mel error message in the python traceback, and, if they are enabled, line numbers!

    For example, in the example below we redeclare the myScript procedure with a line that will result in an error:

        >>> commandEcho(lineNumbers=1)  # turn line numbers on
        >>> mel.eval( '''
        ... global proc myScript( string $stringArg, float $floatArray[] ){
        ...     float $donuts = `ls -type camera`;}
        ... ''')
        >>> mel.myScript( 'foo', [] )
        Traceback (most recent call last):
            ...
        MelConversionError: Error during execution of MEL script: line 2: ,Cannot convert data of type string[] to type float.,
        Calling Procedure: myScript, in Mel procedure entered interactively.
          myScript("foo",{})

    Notice that the error raised is a `MelConversionError`.  There are several MEL exceptions that may be raised,
    depending on the type of error encountered: `MelError`, `MelConversionError`, `MelArgumentError`, `MelSyntaxError`, and `MelUnknownProcedureError`.

    Here's an example showing a `MelArgumentError`, which also demonstrates the additional traceback
    information that is provided for you, including the file of the calling script.

        >>> mel.startsWith('bar') # doctest: +ELLIPSIS
        Traceback (most recent call last):
          ...
        MelArgumentError: Error during execution of MEL script: Line 1.18: ,Wrong number of arguments on call to startsWith.,
        Calling Procedure: startsWith, in file "..."
          startsWith("bar")

    Lastly, an example of `MelUnknownProcedureError`

        >>> mel.poop()
        Traceback (most recent call last):
          ...
        MelUnknownProcedureError: Error during execution of MEL script: line 1: ,Cannot find procedure "poop".,

    .. note:: To remain backward compatible with maya.cmds, all MEL exceptions inherit from `MelError`, which in turn inherits from `RuntimeError`.


    """
    # proc is not an allowed name for a global procedure, so it's safe to use as an attribute
    proc = None
    def __getattr__(self, command):
        if command.startswith('__') and command.endswith('__'):
            try:
                return self.__dict__[command]
            except KeyError:
                raise AttributeError, "object has no attribute '%s'" % command

        def _call(*args, **kwargs):

            strArgs = [pythonToMel(arg) for arg in args]

            if kwargs:
                # keyword args trigger us to format as a command rather than a procedure
                strFlags = [ '-%s %s' % ( key, pythonToMel(val) ) for key, val in kwargs.items() ]
                cmd = '%s %s %s' % ( command, ' '.join( strFlags ), ' '.join( strArgs ) )
            else:
                # procedure
                cmd = '%s(%s)' % ( command, ','.join( strArgs ) )

            try:
                self.__class__.proc = command
                return self.eval(cmd)
            finally:
                self.__class__.proc = None
        return _call


    @classmethod
    def mprint( cls, *args):
        """mel print command in case the python print command doesn't cut it. i have noticed that python print does not appear
        in certain output, such as the rush render-queue manager."""
        #print r"""print (%s\\n);""" % pythonToMel( ' '.join( map( str, args)))
        _mm.eval( r"""print (%s);""" % pythonToMel( ' '.join( map( str, args))) + '\n' )

    @classmethod
    def source( cls, script, language='mel' ):
        """use this to source mel or python scripts.
        language : 'mel', 'python'
            When set to 'python', the source command will look for the python equivalent of this mel file, if
            it exists, and attempt to import it. This is particularly useful when transitioning from mel to python
            via mel2py, with this simple switch you can change back and forth from sourcing mel to importing python.

        """

        if language == 'mel':
            cls.eval( """source "%s";""" % script )

        elif language == 'python':
            script = util.path( script )
            modulePath = script.namebase
            folder = script.parent
            print modulePath
            if not sys.modules.has_key(modulePath):
                print "importing"
                module = __import__(modulePath, globals(), locals(), [''])
                sys.modules[modulePath] = module

        else:
            raise TypeError, "language keyword expects 'mel' or 'python'. got '%s'" % language

    @classmethod
    def eval( cls, cmd ):
        """
        evaluate a string as a mel command and return the result.

        Behaves like maya.mel.eval, with several improvements:
            - returns pymel `Vector` and `Matrix` classes
            - when an error is encountered a `MelError` exception is raised, along with the line number (if enabled) and exact mel error.

        >>> mel.eval( 'attributeExists("persp", "translate")' )
        0
        >>> mel.eval( 'interToUI( "fooBarSpangle" )' )
        u'Foo Bar Spangle'

        """
        # should return a value, like _mm.eval
        #return _mm.eval( cmd )
        # get this before installing the callback
        undoState = _mc.undoInfo(q=1, state=1)
        lineNumbers = _mc.commandEcho(q=1,lineNumbers=1)
        _mc.commandEcho(lineNumbers=1)
        global errors
        errors = [] # a list to store each error line
        def errorCallback( nativeMsg, messageType, data ):
            global errors
            if messageType == _api.MCommandMessage.kError:
                if nativeMsg:
                    errors +=  [ nativeMsg ]

        # setup the callback:
        # assigning ids to a list avoids the swig memory leak warning, which would scare a lot of people even though
        # it is harmless.  hoping we get a real solution to this so that we don't have to needlessly accumulate this data
        id = _api.MCommandMessage.addCommandOutputCallback( errorCallback, None )


        try:
            res = _api.MCommandResult()
            _api.MGlobal.executeCommand( cmd, res, False, undoState )
        except Exception:
            # these two lines would go in a finally block, but we have to maintain python 2.4 compatibility for maya 8.5
            _api.MMessage.removeCallback( id )
            _mc.commandEcho(lineNumbers=lineNumbers)
            # 8.5 fix
            if hasattr(id, 'disown'):
                id.disown()

            msg = '\n'.join( errors )

            if 'Cannot find procedure' in msg:
                e = MelUnknownProcedureError
            elif 'Wrong number of arguments' in msg:
                e = MelArgumentError
                if cls.proc:
                    # remove the calling proc, it will be added below
                    msg = msg.split('\n', 1)[1].lstrip()
            elif 'Cannot convert data' in msg or 'Cannot cast data' in msg:
                e = MelConversionError
            elif 'Syntax error' in msg:
                e = MelSyntaxError
            else:
                e = MelError
            message = "Error during execution of MEL script: %s" % ( msg )
            fmtCmd = '\n'.join( [ '  ' + x for x in cmd.split('\n') ] )


            if cls.proc:
                if e is not MelUnknownProcedureError:
                    file = _mm.eval('whatIs "%s"' % cls.proc)
                    if file.startswith( 'Mel procedure found in: '):
                        file = 'file "%s"' % os.path.realpath(file.split(':')[1].lstrip())
                    message += '\nCalling Procedure: %s, in %s' % (cls.proc, file )
                    message += '\n' + fmtCmd
            else:
                message += '\nScript:\n%s' % fmtCmd
            raise e, message
        else:
            # these two lines would go in a finally block, but we have to maintain python 2.4 compatibility for maya 8.5
            _api.MMessage.removeCallback( id )
            _mc.commandEcho(lineNumbers=lineNumbers)
            # 8.5 fix
            if hasattr(id, 'disown'):
                id.disown()
            resType = res.resultType()

            if resType == _api.MCommandResult.kInvalid:
                return
            elif resType == _api.MCommandResult.kInt:
                result = _api.SafeApiPtr('int')
                res.getResult(result())
                return result.get()
            elif resType == _api.MCommandResult.kIntArray:
                result = _api.MIntArray()
                res.getResult(result)
                return [ result[i] for i in range( result.length() ) ]
            elif resType == _api.MCommandResult.kDouble:
                result = _api.SafeApiPtr('double')
                res.getResult(result())
                return result.get()
            elif resType == _api.MCommandResult.kDoubleArray:
                result = _api.MDoubleArray()
                res.getResult(result)
                return [ result[i] for i in range( result.length() ) ]
            elif resType == _api.MCommandResult.kString:
                return res.stringResult()
            elif resType == _api.MCommandResult.kStringArray:
                result = []
                res.getResult(result)
                return result
            elif resType == _api.MCommandResult.kVector:
                result = _api.MVector()
                res.getResult(result)
                return datatypes.Vector(result)
            elif resType == _api.MCommandResult.kVectorArray:
                result = _api.MVectorArray()
                res.getResult(result)
                return [ datatypes.Vector(result[i]) for i in range( result.length() ) ]
            elif resType == _api.MCommandResult.kMatrix:
                result = _api.MMatrix()
                res.getResult(result)
                return datatypes.Matrix(result)
            elif resType == _api.MCommandResult.kMatrixArray:
                result = _api.MMatrixArray()
                res.getResult(result)
                return [ datatypes.Matrix(result[i]) for i in range( result.length() ) ]

    @staticmethod
    def error( msg, showLineNumber=False ):
        if showLineNumber:
            flags = ' -showLineNumber true '
        else:
            flags = ''
        _mm.eval( """error %s %s""" % ( flags, pythonToMel( msg) ) )

    @staticmethod
    def warning( msg, showLineNumber=False ):
        if showLineNumber:
            flags = ' -showLineNumber true '
        else:
            flags = ''
        _mm.eval( """warning %s %s""" % ( flags, pythonToMel( msg) ) )

    @staticmethod
    def trace( msg, showLineNumber=False ):
        if showLineNumber:
            flags = ' -showLineNumber true '
        else:
            flags = ''
        _mm.eval( """trace %s %s""" % ( flags, pythonToMel( msg) ) )

    @staticmethod
    def tokenize( *args ):
        raise NotImplementedError, "Calling the mel command 'tokenize' from python will crash Maya. Use the string split method instead."

mel = Mel()


def conditionExists(conditionName):
    """
    Returns True if the named condition exists, False otherwise.

    Note that 'condition' here refers to the type used by 'isTrue' and 'scriptJob', NOT to the condition NODE.
    """
    return conditionName in cmds.scriptJob(listConditions=True)


#class MayaGlobals(object):
#    """
#    A Singleton class to represent Maya current optionVars and settings which are global
#    to all of maya and are not saved with the scene.
#    """
#    __metaclass__ = util.Singleton
#
#    optionVars = OptionVarDict()
#    #grid = Grid()
#    #playbackOptions = PlaybackOptions()
#
#    # TODO : create a wrapper for os.environ which allows direct appending and popping of individual env entries (i.e. make ':' transparent)
#    envVars = os.environ
#    @staticmethod
#    def setConstructionHistory( state ):
#        cmds.constructionHistory( tgl=state )
#    @staticmethod
#    def getConstructionHistory(self):
#        return cmds.constructionHistory( q=True, tgl=True )
#
#    @staticmethod
#    def setUpAxis( axis, rotateView=False ):
#        """This flag specifies the axis as the world up direction. The valid axis are either 'y' or 'z'."""
#        cmds.upAxis( axis=axis.lower(), rotateView=rotateView )
#
#    @staticmethod
#    def getUpAxis(self):
#        """This flag gets the axis set as the world up direction. The valid axis are either 'y' or 'z'."""
#        return cmds.upAxis( q=True, axis=True )
#
#    @staticmethod
#    def user():
#        return getuser()
#
#    @staticmethod
#    def host():
#        return gethostname()
#

#class SceneGlobals(object):
#    """
#    A Static Singleton class to represent scene-dependent settings.
#    """
#    __metaclass__ = util.Singleton
#
#    @staticmethod
#    def sceneName():
#        return system.Path(cmds.file( q=1, sn=1))
#
#    @util.universalmethod
#    def getTime(obj):
#        return cmds.currentTime( q=1 )
#
#    @util.universalmethod
#    def setTime( obj, val ):
#        cmds.currentTime( val )
#    time = property( getTime, setTime )
#
#    @staticmethod
#    def getMinTime():
#        return cmds.playbackOptions( q=1, minTime=1 )
#    @staticmethod
#    def setMinTime( val ):
#        cmds.playbackOptions( minTime=val )
#    minTime = property( getMinTime, setMinTime )
#
#    @staticmethod
#    def getMaxTime():
#        return cmds.playbackOptions( q=1, maxTime=1 )
#    @staticmethod
#    def setMaxTime( val ):
#        cmds.playbackOptions( maxTime=val )
#
#    maxTime = property( getMaxTime, setMaxTime )

#env = Env()

_factories.createFunctions( __name__ )
