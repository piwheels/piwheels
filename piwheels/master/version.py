import packaging.version

from .vendor.version import LegacyVersion

def _parse_version(v):                            
    try:                                         
        return packaging.version.Version(v)      
    except packaging.version.InvalidVersion:     
        return LegacyVersion(v)

def parse_version(s):
    v = _parse_version(s)
    # Keep a reference to the original string as otherwise it's unrecoverable;
    # e.g. 0.1a parses to 0.1a0. As this is different, keyed lookups with the
    # parsed variant will fail
    v.original = s
    return v