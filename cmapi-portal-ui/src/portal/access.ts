// What GET /api/v1/me says the person may do in one environment. The browser reads no role from the token: each answer
// here comes from the API's `access` and `operator` fields (docs/14), and the API checks every write again on its token.
import type { Me } from "../api/hooks";

/**
 * Whether a held role grants the permission in the environment (access.roles). A role can be limited to some environments
 * (docs/14, "environments"), and the API answers 403 environment-forbidden outside them, so a permission held somewhere
 * (access.permissions) is not enough to show a control.
 */
export const grantsIn = (access: Me["access"], permission: string, env: string | null | undefined): boolean =>
  access.roles.some((r) => r.permissions.includes(permission) && (r.environments === "all" || (!!env && r.environments.includes(env))));

/** Whether the person is an operator in the environment (#366): /me's `operator` and `operatorEnvironments`. */
export const operatorIn = (me: Me, env: string | null | undefined): boolean =>
  me.operator && (me.operatorEnvironments === "all" || (!!env && me.operatorEnvironments.includes(env)));

/** The label an operator sets to protect a namespace from a delete request, and the one value that protects (#366). */
export const PROTECT_KEY = "cmapi.net/protected";
export const PROTECT_VALUE = "true";
