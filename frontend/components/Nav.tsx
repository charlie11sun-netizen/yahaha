"use client";

import { usePathname, useRouter } from "next/navigation";
import { Box, ClipboardList, Save } from "lucide-react";

import { useAuth } from "@/lib/auth";

function navClass(path: string, target: string) {
  return path === target ? "is-active" : "";
}

export default function Nav() {
  const { user, logout } = useAuth();
  const path = usePathname();
  const router = useRouter();
  const isCreate = path === "/create";

  const goCreate = () => router.push(user ? "/create" : "/login?intent=create");
  const emitCreateEvent = (name: string) => {
    if (typeof window !== "undefined") {
      window.dispatchEvent(new Event(name));
    }
  };

  return (
    <nav className={`pf-topnav${isCreate ? " is-create" : ""}`} aria-label="Main navigation">
      <div className="pf-topnav-inner">
        <button className="pf-brand" onClick={() => router.push("/")} type="button">
          <span className="pf-logo-mark">
            <Box size={18} />
          </span>
          <span>PlayForge AI</span>
        </button>

        <div className="pf-navlinks">
          <button className={navClass(path, "/")} onClick={() => router.push("/")} type="button">
            Explore
          </button>
          <button className={navClass(path, "/create")} onClick={goCreate} type="button">
            Create
          </button>
          <button className={navClass(path, "/me")} onClick={() => router.push(user ? "/me" : "/login")} type="button">
            My Games
          </button>
          <button onClick={() => router.push("/#how")} type="button">
            How It Works
          </button>
        </div>

        <div className="pf-nav-actions">
          {user ? (
            isCreate ? (
              <>
                <button
                  className="pf-task-btn"
                  onClick={() => emitCreateEvent("pf-open-create-tasks")}
                  type="button"
                >
                  <ClipboardList size={17} />
                  My Tasks
                </button>
                <button
                  className="pf-save-draft-btn"
                  onClick={() => emitCreateEvent("pf-save-create-draft")}
                  type="button"
                >
                  <Save size={17} />
                  Save Draft
                </button>
                <button className="pf-create-avatar" onClick={() => router.push("/me")} type="button" aria-label="My games">
                  {user.init}
                </button>
              </>
            ) : (
              <>
                <button className="pf-user-chip" onClick={() => router.push("/me")} type="button">
                  <span>{user.init}</span>
                  {user.name}
                </button>
                <button
                  className="pf-login-btn"
                  onClick={() => {
                    logout();
                    router.push("/");
                  }}
                  type="button"
                >
                  Exit
                </button>
                <button className="pf-start-btn" onClick={goCreate} type="button">
                  Start Creating
                </button>
              </>
            )
          ) : (
            <>
              <button className="pf-login-btn" onClick={() => router.push("/login")} type="button">
                Log in
              </button>
              <button className="pf-start-btn" onClick={() => router.push("/login?mode=signup")} type="button">
                Start Creating
              </button>
            </>
          )}
        </div>
      </div>
    </nav>
  );
}
