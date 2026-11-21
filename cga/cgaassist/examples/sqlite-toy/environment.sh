PAIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SQLITE_PREFIX="$PAIR/dependencies/root"
SQLITE_LIBRARY="$(find "$SQLITE_PREFIX/usr/lib" -name libsqlite3.so -print -quit)"
if [ ! -r "$SQLITE_PREFIX/usr/include/sqlite3.h" ] || [ ! -r "$SQLITE_LIBRARY" ]; then
    echo "Missing SQLite dependency under $SQLITE_PREFIX" >&2
    return 1
fi
SQLITE_LIBDIR="$(dirname "$SQLITE_LIBRARY")"
export CPATH="$SQLITE_PREFIX/usr/include${CPATH:+:$CPATH}"
export LIBRARY_PATH="$SQLITE_LIBDIR${LIBRARY_PATH:+:$LIBRARY_PATH}"
export LD_LIBRARY_PATH="$SQLITE_LIBDIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export CODEQL_JAVA_HOME="${CODEQL_JAVA_HOME:-/usr}"
export CGAST_TMPDIR="${CGAST_TMPDIR:-$PAIR/.cga/tmp/artifacts}"
