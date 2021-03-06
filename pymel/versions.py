"""
Contains functions for easily comparing versions of Maya with the current running version.
Class for storing apiVersions, which are the best method for comparing versions. ::

    >>> from pymel import versions
    >>> if versions.current() >= versions.v2008:
    ...     print "The current version is later than Maya 2008"
    The current version is later than Maya 2008
"""

import re
from maya.OpenMaya import MGlobal  as _MGlobal

def parseVersionStr(versionStr, extension=False):
    """
    >>> from pymel.all import *
    >>> versions.parseVersionStr('2008 Service Pack1 x64')
    '2008'
    >>> versions.parseVersionStr('2008 Service Pack1 x64', extension=True)
    '2008-x64'
    >>> versions.parseVersionStr('2008x64', extension=True)
    '2008-x64'
    >>> versions.parseVersionStr('8.5', extension=True)
    '8.5'
    >>> versions.parseVersionStr('2008 Extension 2')
    '2008'
    >>> versions.parseVersionStr('/Applications/Autodesk/maya2009/Maya.app/Contents', extension=True)
    '2009'
    >>> versions.parseVersionStr('C:\Program Files (x86)\Autodesk\Maya2008', extension=True)
    '2008'

    """
    # problem with service packs addition, must be able to match things such as :
    # '2008 Service Pack 1 x64', '2008x64', '2008', '8.5'

    # NOTE: we're using the same regular expression (parseVersionStr) to parse both the crazy human readable
    # maya versions as returned by about, and the maya location directory.  to handle both of these i'm afraid
    # the regular expression might be getting unwieldy

    ma = re.search( "((?:maya)?(?P<base>[\d.]{3,})(?:(?:[ ].*[ ])|(?:-))?(?P<ext>x[\d.]+)?)", versionStr)
    version = ma.group('base')

    if extension and (ma.group('ext') is not None) :
        version += "-"+ma.group('ext')
    return version

_current = _MGlobal.apiVersion()
_fullName = _MGlobal.mayaVersion()
_installName = parseVersionStr(_fullName, extension=True)
_shortName = parseVersionStr(_fullName, extension=False)


v85        = 200700
v85_SP1    = 200701
v2008      = 200800
v2008_SP1  = 200806
v2008_EXT2 = 200806
v2009      = 200900
v2009_EXT1 = 200904
v2009_SP1A = 200906
v2010      = 201000
v2011      = 201100

def current():
    return _current

def fullName():
    return _fullName

def installName():
    return _installName

def shortName():
    return _shortName

def flavor():
    import maya.cmds
    try:
        return maya.cmds.about(product=1).split()[1]
    except AttributeError:
        raise RuntimeError, "This method cannot be used until maya is fully initialized"

def isUnlimited():
    return flavor() == 'Unlimited'


def isComplete():
    return flavor() == 'Complete'


def isRenderNode():
    return flavor() == 'Render'


def isEval():
    import maya.cmds
    try:
        return maya.cmds.about(evalVersion=1)
    except AttributeError:
        raise RuntimeError, "This method cannot be used until maya is fully initialized"

