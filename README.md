# artlink

A package for packaging, organizing, and combining artifacts

[![Build Status](https://github.com/dau-dev/artlink/actions/workflows/build.yaml/badge.svg?branch=main&event=push)](https://github.com/dau-dev/artlink/actions/workflows/build.yaml)
[![codecov](https://codecov.io/gh/dau-dev/artlink/branch/main/graph/badge.svg)](https://codecov.io/gh/dau-dev/artlink)
[![License](https://img.shields.io/github/license/dau-dev/artlink)](https://github.com/dau-dev/artlink)
[![PyPI](https://img.shields.io/pypi/v/artlink.svg)](https://pypi.python.org/pypi/artlink)

## Overview

`artlink` owns the DAU-neutral artifact manifest and bundle model. The current YAML schema is `artlink.artifact-manifest/v0`; it records source artifacts, metadata artifacts, binary artifacts, artifact roles, source languages, provided modules, media types, and optional digests in a Pydantic/JSON-friendly shape.

The bundle loader validates reusable artifact packages before a build system consumes them. It checks missing files, required roles, HDL source availability, unsupported source languages, duplicate module providers, and provenance for artifacts loaded from manifests.

> [!NOTE]
> This library was generated using [copier](https://copier.readthedocs.io/en/stable/) from the [Base Python Project Template repository](https://github.com/python-project-templates/base).
