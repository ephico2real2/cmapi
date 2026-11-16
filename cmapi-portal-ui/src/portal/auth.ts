// The portal's sign-in: OpenID Connect Authorization Code with PKCE, through the public client of config.json.
// RFC 10017 (BCP 212, OAuth 2.0 for Browser-Based Applications) is the standard for each choice here.
import { InMemoryWebStorage, UserManager, WebStorageStateStore } from "oidc-client-ts";
import type { SigninSilentArgs, SignoutRedirectArgs, User, UserManagerSettings } from "oidc-client-ts";
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

/** Serializes automatic/API renewals and drains them before removing the user at sign-out. */
class PortalUserManager extends UserManager {
  private pendingRenewal: Promise<User | null> | undefined;
  private pendingSignout: Promise<void> | undefined;
  private closing = false;

  constructor(...args: ConstructorParameters<typeof UserManager>) {
    super(...args);
    const service = this.metadataService;
    const getMetadata = service.getMetadata.bind(service);
    service.getMetadata = async () => {
      const metadata = await getMetadata();
      for (const key of ["authorization_endpoint", "token_endpoint", "end_session_endpoint", "userinfo_endpoint", "jwks_uri"] as const) {
        const endpoint = metadata[key];
        if (!endpoint) continue;
        const url = new URL(endpoint);
        const local = url.protocol === "http:" && ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
        if (url.protocol !== "https:" && !local) throw new Error(`OIDC ${key} must be an https URL.`);
        if (url.username || url.password) throw new Error(`OIDC ${key} must have no user.`);
      }
      return metadata;
    };
  }

  override signinSilent(args?: SigninSilentArgs): Promise<User | null> {
    if (this.closing) return Promise.resolve(null);
    return this.pendingRenewal ??= super.signinSilent({ ...args, silentRequestTimeoutInSeconds: args?.silentRequestTimeoutInSeconds ?? this.settings.silentRequestTimeoutInSeconds }).finally(() => { this.pendingRenewal = undefined; });
  }

  /**
   * Ends the session at the issuer. OpenID Connect RP-Initiated Logout 1.0, section 2: id_token_hint is RECOMMENDED,
   * and without it the issuer must ask the person to confirm. The same section says that the issuer supports POST.
   * So the ID token goes in the body of a form POST, and no token is in a URL, a history entry or an access log line.
   */
  override signoutRedirect(_args?: SignoutRedirectArgs): Promise<void> {
    if (this.pendingSignout) return this.pendingSignout;
    this.closing = true;
    this.stopSilentRenew();
    this.pendingSignout = (async () => {
      // A renewal that is in flight would store a new user after the removal below. Wait for it first.
      await this.pendingRenewal?.catch(() => undefined);
      const user = await this.getUser();
      const endpoint = await this.metadataService.getEndSessionEndpoint();
      await this.removeUser();
      if (!endpoint) throw new Error("The issuer names no end-session endpoint.");
      const fields: Record<string, string> = { client_id: this.settings.client_id };
      if (user?.id_token) fields.id_token_hint = user.id_token;
      if (this.settings.post_logout_redirect_uri) fields.post_logout_redirect_uri = this.settings.post_logout_redirect_uri;
      await this.leave(endpoint, fields);
    })().finally(() => { this.pendingSignout = undefined; });
    return this.pendingSignout;
  }

  /** Sends the browser away with a form POST. The promise does not settle: the page ends with the navigation. */
  leave(endpoint: string, fields: Record<string, string>): Promise<void> {
    const form = document.createElement("form");
    form.method = "post";
    form.action = endpoint;
    for (const [name, value] of Object.entries(fields)) {
      const input = document.createElement("input");
      input.type = "hidden";
      input.name = name;
      input.value = value;
      form.append(input);
    }
    document.body.append(form);
    form.submit();
    return new Promise(() => {});
  }
}

export function oidcSettings(config: PortalConfig): AuthProviderProps {
  // The redirect URI is this page without its query and fragment. The realm lists it for the client.
  const page = location.origin + location.pathname;
  const settings: UserManagerSettings = {
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
    requestTimeoutInSeconds: 10,
    // No check_session iframe: browsers block the third-party cookie that it needs.
    monitorSession: false,
    // The portal reads the person from GET /api/v1/me, not from the userinfo endpoint.
    loadUserInfo: false,
  };
  return {
    userManager: new PortalUserManager(settings),
    // The code and the state are used once. Take them out of the address bar and the history.
    onSigninCallback: (user) => history.replaceState(null, "", location.pathname + returnHash(user))
  };
}
