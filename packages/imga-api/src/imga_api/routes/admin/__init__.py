"""Super-admin / cross-tenant routes (Sprint 7.5.5).

Mounted under ``/admin/...`` to keep the namespace clear from the
tenant-scoped surface (``/tenants/me/...``, ``/tickets/...``). Every
endpoint here uses the ``imga_admin`` DB role (BYPASSRLS) because
super-admin operations cross tenant boundaries.
"""
