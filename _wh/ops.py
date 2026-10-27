"""
Calling another add-on's operator (contract v2.1, R7). On Blender 5.3
`hasattr(bpy.ops.<module>, "<name>")`, and even
`hasattr(bpy.ops, "<module>")`, is ALWAYS True, because bpy.ops hands out a proxy for any name;
the call then fails with "could not be found". `dir()` lists only registered operators, so that
is the test. Pass `bpy.ops` in; this module never imports bpy.
"""


def operator_exists(ops, idname):
    """True when the operator "module.name" (e.g. "warehouse.make_load") is registered.
    `ops` is bpy.ops."""
    module, _, name = str(idname).partition(".")
    if not module or not name:
        return False
    try:
        return name in dir(getattr(ops, module))
    except Exception:
        return False
