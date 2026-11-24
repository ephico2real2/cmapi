## 0.162.0 (2026-10-23)

Omitted `bool` and `bool | None` form fields now use their declared defaults or produce missing-field errors, consistent with other fields and Pydantic behavior. FastAPI no longer infers `False` for omitted booleans. This applies to individual form parameters, form models, and unions of form models.

Omitted boolean model fields are excluded from `model_dump(exclude_unset=True)`, and their defaults no longer count as submitted fields during union selection. Default factories and `validate_default` follow the usual rules.

For HTML checkboxes, declare a boolean with a default of `False`. See [Boolean Form Fields](https://fastapi.tiangolo.com/tutorial/request-forms/#boolean-form-fields).

### Breaking Changes

* 🐛 Restore default handling for omitted boolean form fields. PR [#16605](https://github.com/fastapi/fastapi/pull/16605) by [@tiangolo](https://github.com/tiangolo).


## 0.160.0 (2026-10-22)

Query, header, cookie, and form parameter models now apply their `extra` configuration to all submitted fields in the same parameter location, consistent with Pydantic behavior. This includes fields declared in other models, individual parameters, or dependencies, which were previously excluded.

With `extra="forbid"`, fields outside the model are rejected even if another parameter declares them. With `extra="allow"`, those fields are included as model extras. With the default `extra="ignore"`, they are ignored.

### Breaking Changes

* 🐛 Apply each parameter model's `extra` configuration to sibling fields. PR [#16594](https://github.com/fastapi/fastapi/pull/16594) by [@tiangolo](https://github.com/tiangolo).


## 0.155.0 (2026-10-20)

The deprecated `**extra` keyword arguments have been removed from `Path`, `Query`, `Header`, `Cookie`, `Body`, `Form`, and `File`. Unknown keyword arguments now raise `TypeError`. For additional JSON Schema properties, replace, for example, `Query(custom="value")` with `Query(json_schema_extra={"custom": "value"})`.

### Breaking Changes

* 🔥 Remove deprecated `**extra` from request parameters. PR [#16545](https://github.com/fastapi/fastapi/pull/16545) by [@tiangolo](https://github.com/tiangolo).


## 0.151.0 (2026-10-20)

JSON request bodies now distinguish an explicit `null` from an omitted value. For individual `Body` parameters, `null` is validated as `None`: nullable types accept it, and non-nullable types reject it even when a default is defined. Defaults and default factories apply only when the value is omitted. This applies both to parameters inside JSON objects and to parameters representing the entire body. Clients that used `null` to request a default should omit the value instead.

When a JSON object is expected because of `Body(embed=True)` or multiple body parameters, sending `null` as the entire body now returns a validation error.

### Breaking Changes

* 🐛 Distinguish JSON null from omitted body values. PR [#16536](https://github.com/fastapi/fastapi/pull/16536) by [@tiangolo](https://github.com/tiangolo).


## 0.150.0 (2026-10-20)

When no file is selected, browsers submit a file part with an empty filename and empty content. FastAPI now treats this as missing: required file fields return a validation error, and fields with defaults or default factories use them. Unselected inputs are ignored in lists of files. Named zero-byte files are still accepted.

### Breaking Changes

* 🐛 Treat unselected browser file inputs as missing. PR [#16534](https://github.com/fastapi/fastapi/pull/16534) by [@tiangolo](https://github.com/tiangolo).


## 0.149.0 (2026-10-19)

Browsers submit empty text inputs as empty strings (`""`). FastAPI now treats empty scalar form values as missing in form models, matching individual `Form` parameters. Required fields return a validation error. Fields with defaults or default factories use them and remain unset in `model_dump(exclude_unset=True)`.

Empty strings inside lists are preserved. Omitted boolean form fields still become `False`. JSON requests and direct Pydantic validation are unchanged.

### Breaking Changes

* 🐛 Treat empty scalar values as missing in form models. PR [#16529](https://github.com/fastapi/fastapi/pull/16529) by [@tiangolo](https://github.com/tiangolo).


## 0.148.0 (2026-10-19)

Defaults for omitted `Query`, `Header`, `Cookie`, and `Form` parameters and model fields are no longer treated as user input. Defaults are not validated unless `validate_default=True` is enabled. If you rely on validators running for omitted values, enable default validation with `Field(validate_default=True)` for model fields or, for example, `Query(validate_default=True)` for individual parameters. `Body(validate_default=True)` is now honored too.

For parameter models, applying a default no longer marks a field as explicitly set, so `model_dump(exclude_unset=True)` excludes it. Default factories run once, and validation errors no longer include injected defaults in `input`.

Omitted boolean form fields still become `False` and count as explicitly set.

### Breaking Changes

* 🐛 Fix default handling for request parameters and models. PR [#16527](https://github.com/fastapi/fastapi/pull/16527) by [@tiangolo](https://github.com/tiangolo).


## 0.147.0 (2026-10-19)

Omitted `bool` and `bool | None` form fields are now interpreted as `False`, matching unchecked HTML checkboxes. This applies to individual `Form` parameters and form models, including required fields and fields with defaults of `True` or `None`. The inferred value is considered explicitly set, including in `model_dump(exclude_unset=True)`.

JSON requests and direct Pydantic validation are unchanged. See [Boolean Form Fields](https://fastapi.tiangolo.com/tutorial/request-forms/#boolean-form-fields).

### Breaking Changes

* 🐛 Treat omitted boolean form fields as False. PR [#16523](https://github.com/fastapi/fastapi/pull/16523) by [@tiangolo](https://github.com/tiangolo).


## 0.146.0 (2026-10-18)

The `root_path` parameter in `FastAPI()` is deprecated. Configure the server with `fastapi run --root-path /api/v1` instead.

### Breaking Changes

* 🗑️ Deprecate the `root_path` parameter in `FastAPI`. PR [#16520](https://github.com/fastapi/fastapi/pull/16520) by [@tiangolo](https://github.com/tiangolo).


## 0.145.0 (2026-10-18)

### Breaking Changes

* 🔥 Remove deprecated `openapi_prefix` and unused `**extra` from `FastAPI`. PR [#16518](https://github.com/fastapi/fastapi/pull/16518) by [@tiangolo](https://github.com/tiangolo).


## 0.143.0 (2026-10-08)

Automatic OpenTelemetry exporter setup is now opt-in. If you rely on FastAPI to configure exporters from `OTEL_*` environment variables, set `FASTAPI_OTEL_AUTO_CONFIGURE=true` or use `FastAPI(telemetry={"auto_configure": True})` to retain the previous behavior.

Applications that configure their own providers and exporters require no changes. FastAPI Cloud enables automatic setup for you.

### Breaking Changes

* 💥 Require opt-in for automatic OpenTelemetry exporter setup. PR [#16476](https://github.com/fastapi/fastapi/pull/16476) by [@tiangolo](https://github.com/tiangolo).


## 0.137.0 (2026-06-14)

### Breaking Changes

* ♻️ Refactor internals to preserve `APIRouter` and `APIRoute` instances. PR [#15745](https://github.com/fastapi/fastapi/pull/15745) by [@tiangolo](https://github.com/tiangolo).

Unblocks ✨ SO MANY THINGS ✨

Before this, `router.include_router(other_router)` would take each path operation from `other_router` and "clone" it, or recreate it from scratch.

This would mean that in the end there was only one top level router, part of the app.

The way it is structured here is that there are a few additional classes to handle intermediate metadata for router and route inclusion. That way the information of "router X includes Y and Y includes Z" is stored somewhere, without affecting (recreating / cloning) the final route.

#### Non Objectives

Dependencies for 404: previously I intended to support dependencies that would be executed even for 404, but that would conflict with the fact that a router could _not_ find a match, but the next router _did_ find a match. Executing dependencies in the router that did not find a match would not make sense, they could consume the request, body, etc. This original idea was discarded.

#### Specific Breaking Changes

Now `router.routes` is no longer a plain list of `APIRoute` objects, it can contain these intermediate objects that can contain additional routers, forming a tree.

Any logic that depended on iterating on the `router.routes` directly would be affected, that logic cannot expect to be able to extract data from a plain list of routes, as it's no longer a plain list but a tree.

Additionally, any logic that iterated on `router.routes` to modify them would now also see these new objects, and would not see all the routes in the app.

`router.routes` should be considered an internal implementation detail, only passed around to the FastAPI functions that need it.

#### Features

* Adding routes (path operations) after a router is included now works, they are reflected as they are not copied.
* Including `subrouter` in `mainrouter` can be done before adding routes (path operations) to `subrouter`, because now the entire object is stored instead of copying the routes.
* As routes are not copied, in some cases that might save some memory.

#### Alpha Features

This is not documented yet, so it's not officially supported yet and could change in the future.

But, as `APIRoute` and `APIRouter` instances are now preserved, they could be customized.

`APIRouter` has two new methods, `.matches()` and `.handle()`, counterpart to the existing ones in `APIRoute`. With this a router could customize how it matches and handles requests. For example, it could match only requests that include some specific header, for example for handling versions in headers.

Still, for now, consider this very experimental and potentially changing and breaking in the future.

#### Future Features Enabled

* Custom `APIRoute` subclasses (undocumented, but already works as described above)
* Custom `APIRouter` subclasses (undocumented, but already works as described above)
* Dependencies per router
* Exception handlers per router
* Middleware per router
* Other features planned


## 0.132.0 (2026-02-23)

### Breaking Changes

* 🔒️ Add `strict_content_type` checking for JSON requests. PR [#14978](https://github.com/fastapi/fastapi/pull/14978) by [@tiangolo](https://github.com/tiangolo).
    * Now FastAPI checks, by default, that JSON requests have a `Content-Type` header with a valid JSON value, like `application/json`, and rejects requests that don't.
    * If the clients for your app don't send a valid `Content-Type` header you can disable this with `strict_content_type=False`.
    * Check the new docs: [Strict Content-Type Checking](https://fastapi.tiangolo.com/advanced/strict-content-type/).


## 0.131.0 (2026-02-22)

### Breaking Changes

* 🗑️ Deprecate `ORJSONResponse` and `UJSONResponse`. PR [#14964](https://github.com/fastapi/fastapi/pull/14964) by [@tiangolo](https://github.com/tiangolo).


## 0.129.0 (2026-02-12)

### Breaking Changes

* ➖ Drop support for Python 3.9. PR [#14897](https://github.com/fastapi/fastapi/pull/14897) by [@tiangolo](https://github.com/tiangolo).

### Refactors

* 🎨 Update internal types for Python 3.10. PR [#14898](https://github.com/fastapi/fastapi/pull/14898) by [@tiangolo](https://github.com/tiangolo).


## 0.128.0 (2025-12-27)

### Breaking Changes

* ➖ Drop support for `pydantic.v1`. PR [#14609](https://github.com/fastapi/fastapi/pull/14609) by [@tiangolo](https://github.com/tiangolo).


## 0.127.0 (2025-12-21)

### Breaking Changes

* 🔊 Add deprecation warnings when using `pydantic.v1`. PR [#14583](https://github.com/fastapi/fastapi/pull/14583) by [@tiangolo](https://github.com/tiangolo).


## 0.125.0 (2025-12-17)

### Breaking Changes

* 🔧 Drop support for Python 3.8. PR [#14563](https://github.com/fastapi/fastapi/pull/14563) by [@tiangolo](https://github.com/tiangolo).
    * This would actually not be a _breaking_ change as no code would really break. Any Python 3.8 installer would just refuse to install the latest version of FastAPI and would only install 0.124.4. Only marking it as a "breaking change" to make it visible.

### Refactors

* ♻️ Upgrade internal syntax to Python 3.9+ 🎉. PR [#14564](https://github.com/fastapi/fastapi/pull/14564) by [@tiangolo](https://github.com/tiangolo).


## 0.120.0 (2025-10-23)

There are no major nor breaking changes in this release. ☕️

The internal reference documentation now uses `annotated_doc.Doc` instead of `typing_extensions.Doc`, this adds a new (very small) dependency on [`annotated-doc`](https://github.com/fastapi/annotated-doc), a package made just to provide that `Doc` documentation utility class.

I would expect `typing_extensions.Doc` to be deprecated and then removed at some point from `typing_extensions`, for that reason there's the new `annotated-doc` micro-package. If you are curious about this, you can read more in the repo for [`annotated-doc`](https://github.com/fastapi/annotated-doc).

This new version `0.120.0` only contains that transition to the new home package for that utility class `Doc`.


