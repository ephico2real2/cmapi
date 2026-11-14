// The portal's sign-in: OpenID Connect Authorization Code with PKCE, through the public client of config.json.
// RFC 10017 (BCP 212, OAuth 2.0 for Browser-Based Applications) is the standard for each choice here.
import { InMemoryWebStorage, WebStorageStateStore } from "oidc-client-ts";
import type { User } from "oidc-client-ts";
import type { AuthProviderProps } from "react-oidc-context";
import type { PortalConfig } from "./config";

/** What the portal keeps through the redirect to the issuer: the view to return to. */
export interface ReturnState {
  hash: string;
}

/** Only a fragment of this page is a place to return to. The value comes back through storage, so it is checked. */
function returnHash(user: User | undefined): string {
  const state = user?.state as Partial<ReturnState> | undefined;
  return typeof state?.hash === "string" && /^#[\w/?=&%.~+-]*$/.test(state.hash) ? state.hash : "";
}

export function oidcSettings(config: PortalConfig): AuthProviderProps {
  // The redirect URI is this page without its query and fragment. The realm lists it for the client.
  const page = location.origin + location.pathname;
  return {
    authority: config.issuer,
    client_id: config.clientId,
    redirect_uri: page,
    post_logout_redirect_uri: page,
    response_type: "code",
    response_mode: "query",
    // The realm gives the client its scopes as defaults (audience, roles, identity), so the portal asks for no more.
    scope: "openid",
    // Tokens stay in the memory of this page (RFC 10017 section 8.4): nothing is written to localStorage or
    // sessionStorage, and nothing is left on disk (section 8.6). A reload signs in again through the issuer's session.
    userStore: new WebStorageStateStore({ store: new InMemoryWebStorage() }),
    // The PKCE verifier and the state must survive the redirect. sessionStorage holds them for this tab only, and
    // oidc-client-ts removes the entry when the code is exchanged. Its own default is localStorage.
    stateStore: new WebStorageStateStore({ store: window.sessionStorage }),
    // The access token lives 5 minutes. The library renews it with the refresh token before it ends.
    automaticSilentRenew: true,
    // No check_session iframe: browsers block the third-party cookie that it needs.
    monitorSession: false,
    // The portal reads the person from GET /api/v1/me, not from the userinfo endpoint.
    loadUserInfo: false,
    // The code and the state are used once. Take them out of the address bar and the history.
    onSigninCallback: (user) => history.replaceState(null, "", location.pathname + returnHash(user))
  };
}
