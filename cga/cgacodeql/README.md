# `cga codeql` — CodeQL toolchain checks

```sh
cga codeql check \
  --version 2.27.1 \
  --system Linux \
  --machine aarch64 \
  --machine arm64 \
  --pack codeql/cpp-all@12.1.1
```

`check` records the resolved CodeQL version, host platform, and hashes of
required files in `cgacodeql-check`. Pack specifications resolve relative to
the selected CodeQL executable's bundle tree. This command validates the
toolchain only; it does not plan or build databases.
