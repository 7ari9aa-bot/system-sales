import { describe, expect, it } from "vitest";

import { metaOauthProvider } from "./ChannelsSettings.jsx";

describe("metaOauthProvider", () => {
  it("links Instagram through Instagram Login by default", () => {
    expect(metaOauthProvider("instagram", "login")).toBe("instagram_login");
    expect(metaOauthProvider("instagram", undefined)).toBe("instagram_login");
  });

  it("keeps Facebook Login for a merchant whose account hangs off a Page", () => {
    expect(metaOauthProvider("instagram", "facebook")).toBe("instagram");
  });

  it("never rewrites another channel", () => {
    expect(metaOauthProvider("messenger", "login")).toBe("messenger");
    expect(metaOauthProvider("facebook", "login")).toBe("facebook");
  });
});
