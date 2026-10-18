# Repository instructions

Follow [_agent/rules/repository-relative-paths.mdc](_agent/rules/repository-relative-paths.mdc)
when editing any code, configuration, notebook, or documentation in this repository.

- Use repository-relative paths; state when commands start in a repository subdirectory.
- Never embed a developer's drive, username, checkout directory, or WSL mount in source or examples.
- Resolve paths from the relevant source-file location at runtime when independence from the
  working directory is required. Do not replace runtime discovery with hardcoded absolute paths.
- Keep unavoidable container-internal paths, API routes, and URLs distinct from checkout paths.
- Clear saved notebook outputs before publishing; they can expose local paths or private data.
