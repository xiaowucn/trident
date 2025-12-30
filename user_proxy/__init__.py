import re

from sqlalchemy.dialects.postgresql.base import PGDialect, RESERVED_WORDS

# PATCH 信创数据库添加了关键字
RESERVED_WORDS.add('level')
RESERVED_WORDS.add('start')


def patch_get_server_version_info(self, connection):
    v = connection.execute("select version()").scalar()
    m = re.match(
        r".*(?:PostgreSQL|EnterpriseDB|LightDB|KingbaseES) " r"(\d+)\.?(\d+)?(?:\.(\d+))?(?:\.\d+)?(?:devel|beta)?",
        v,
    )
    if not m:
        if re.match(r'KingbaseES V|gaussdb', v):
            return 9, 6, 0
        raise AssertionError("Could not determine version from string '%s'" % v)
    return tuple([int(x) for x in m.group(1, 2, 3) if x is not None])


PGDialect._get_server_version_info = patch_get_server_version_info
