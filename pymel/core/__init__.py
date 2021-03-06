"The primary module for maya commands and node classes"

#import pymel._internal as _internal

import sys
import pymel as _pymel
_pymel.core = sys.modules[__name__]
import pymel.versions as _versions
import pymel.internal as _internal

# will check for the presence of an initilized Maya / launch it
_internal.mayaInit()

import pymel.internal.factories as _factories
import pymel.internal.pmcmds as _pmcmds
_pmcmds.addAllWrappedCmds()

import pymel.api as _api
from general import *
from context import *
from system import *
from windows import *
from animation import *
from effects import *
from modeling import *
from rendering import *
from language import *
from other import *

# to allow lazy loading, we avoid import *
import nodetypes
import nodetypes as nt
import datatypes
import datatypes as dt
import uitypes
import uitypes as ui

import runtime

# initialize MEL
_internal.finalize()

import maya.cmds as cmds

# these modules are imported anyway so they should not be a performance hit
import pymel.util as util
import pymel.api as api

_logger = _internal.getLogger(__name__)

#: dictionary of plugins and the nodes and commands they register
_pluginData = {}

_module = sys.modules[__name__]

def _pluginLoaded( *args ):

    if len(args) > 1:
        # 2009 API callback, the args are ( [ pathToPlugin, pluginName ], clientData )
        pluginName = args[0][1]
    else:
        pluginName = args[0]

    if not pluginName:
        return

    _logger.debug("Plugin loaded: %s", pluginName)

    _pluginData[pluginName] = {}

    try:
        commands = _pmcmds.pluginInfo(pluginName, query=1, command=1)
    except:
        _logger.error("Failed to get command list from %s", pluginName)
        commands = None


    # Commands
    if commands:
        _pluginData[pluginName]['commands'] = commands
        _logger.debug( "adding new commands: %s" % ', '.join(commands) )
        for funcName in commands:
            _logger.debug("Adding command: %s..." % funcName)
            #__logger.debug("adding new command:", funcName)
            _factories.cmdlist[funcName] = _factories.cmdcache.getCmdInfoBasic( funcName )
            _pmcmds.addWrappedCmd(funcName)
            func = _factories.functionFactory( funcName )
            try:
                if func:
                    setattr( _module, funcName, func )
                    if 'pymel.all' in sys.modules:
                        setattr( sys.modules['pymel.all'], funcName, func )
                else:
                    _logger.warning( "failed to create function" )
            except Exception, msg:
                _logger.warning("exception: %s" % str(msg) )
            _logger.debug("Done adding command %s" % funcName)

    # Nodes
    mayaTypes = cmds.pluginInfo(pluginName, query=1, dependNode=1)
    #apiEnums = cmds.pluginInfo(pluginName, query=1, dependNodeId=1)
    if mayaTypes :

        def addPluginPyNodes(*args):
            try:
                id = _pluginData[pluginName]['callbackId']
                if id is not None:
                    _api.MEventMessage.removeCallback( id )
                    if hasattr(id, 'disown'):
                        id.disown()
            except KeyError:
                _logger.warning("could not find callback id!")

            _pluginData[pluginName]['dependNodes'] = mayaTypes
            _logger.debug("adding new nodes: %s", ', '.join( mayaTypes ))

            for mayaType in mayaTypes:
                _logger.debug("Adding node: %s..." % mayaType)
                inheritance = _factories.getInheritance( mayaType )

                if not util.isIterable(inheritance):
                    _logger.warn( "could not get inheritance for mayaType %s" % mayaType)
                else:
                    #__logger.debug(mayaType, inheritance)
                    #__logger.debug("adding new node:", mayaType, apiEnum, inheritence)
                    # some nodes in the hierarchy for this node might not exist, so we cycle through all
                    parent = 'dependNode'

                    for node in inheritance:
                        nodeName = _factories.addPyNode( nodetypes, node, parent )
                        parent = node
                        if 'pymel.all' in sys.modules:
                            # getattr forces loading of Lazy object
                            setattr( sys.modules['pymel.all'], nodeName, getattr(nodetypes,nodeName) )
                _logger.debug("Done adding node %s" % mayaType)

        # evidently isOpeningFile is not avaiable in maya 8.5 sp1.  this could definitely cause problems
        if _api.MFileIO.isReadingFile() or ( _versions.current() >= _versions.v2008 and _api.MFileIO.isOpeningFile() ):
            #__logger.debug("pymel: Installing temporary plugin-loaded callback")
            id = _api.MEventMessage.addEventCallback( 'SceneOpened', addPluginPyNodes )
            _pluginData[pluginName]['callbackId'] = id
            # scriptJob not respected in batch mode, had to use _api
            #cmds.scriptJob( event=('SceneOpened',doSomethingElse), runOnce=1 )
        else:
            # add the callback id as None so that if we fail to get an id in addPluginPyNodes we know something is wrong
            _pluginData[pluginName]['callbackId'] = None
            addPluginPyNodes()





def _pluginUnloaded(*args):

    if len(args) > 1:
        # 2009 API callback, the args are
        # ( [ pluginName, pathToPlugin ], clientData )  OR
        # ( [ pathToPlugin ], clientData )
        pluginName = args[0][0]
    else:
        pluginName = args[0]

    _logger.debug("Plugin unloaded: %s" % pluginName)
    try:
        data = _pluginData.pop(pluginName)
    except KeyError:
        pass
    else:
        # Commands
        commands = data.pop('commands', [])
        if commands:
            _logger.info("Removing commands: %s", ', '.join( commands ))
            for command in commands:
                try:
                    _pmcmds.removeWrappedCmd(command)
                    _module.__dict__.pop(command)
                except KeyError:
                    _logger.warn( "Failed to remove %s from module %s" % (command, _module.__name__) )

        # Nodes
        nodes = data.pop('dependNodes', [])
        if nodes:
            _logger.debug("Removing nodes: %s" % ', '.join( nodes ))
            for node in nodes:
                _factories.removePyNode( nodetypes, node )


global _pluginLoadedCB
global _pluginUnloadedCB
_pluginLoadedCB = None
_pluginUnloadedCB = None

def _installCallbacks():
    """install the callbacks that trigger new nodes and commands to be added to pymel when a
    plugin loads.  This is called from pymel.__init__
    """

    global _pluginLoadedCB
    if _pluginLoadedCB is None:
        _pluginLoadedCB = True
        _logger.debug("Adding pluginLoaded callback")
        #_pluginLoadedCB = pluginLoadedCallback(module)


        if _versions.current() >= _versions.v2009:
            id = _api.MSceneMessage.addStringArrayCallback( _api.MSceneMessage.kAfterPluginLoad, _pluginLoaded  )
            if hasattr(id, 'disown'):
                id.disown()
        else:
            # BUG: this line has to be a string, because using a function causes a 'pure virtual' error every time maya shuts down
            cmds.loadPlugin( addCallback='import pymel.core; pymel.core._pluginLoaded("%s")' )
    else:
        _logger.debug("PluginLoaded callback already exists")

    global _pluginUnloadedCB
    if _pluginUnloadedCB is None:
        _pluginUnloadedCB = True

        # BUG: autodesk still has not add python callback support, and calling this as MEL is not getting the plugin name passed to it
        #mel.unloadPlugin( addCallback='''python("import pymel; pymel._pluginUnloaded('#1')")''' )

        if _versions.current() >= _versions.v2009:
            _logger.debug("Adding pluginUnloaded callback")
            id = _api.MSceneMessage.addStringArrayCallback( _api.MSceneMessage.kAfterPluginUnload, _pluginUnloaded )
            if hasattr(id, 'disown'):
                id.disown()


    else:
        _logger.debug("PluginUnloaded callback already exists")

    # add commands and nodes for plugins loaded prior to importing pymel
    preLoadedPlugins = cmds.pluginInfo( q=1, listPlugins=1 )
    if preLoadedPlugins:
        _logger.info("Updating pymel with pre-loaded plugins: %s" % ', '.join( preLoadedPlugins ))
        for plugin in preLoadedPlugins:
            _pluginLoaded( plugin )

_installCallbacks()





