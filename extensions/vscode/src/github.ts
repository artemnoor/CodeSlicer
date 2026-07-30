import * as vscode from "vscode";

/** P1 OAuth seam: no PAT storage, API call, source upload, or publishing happens here. */
export interface GitHubReviewAvailability { status: "not-implemented"; message: string; requiresUserAction: true }
export interface GitHubAuthenticationState { authenticated: boolean; accountLabel?: string; message: string }

export class GitHubReviewService {
  availability(): GitHubReviewAvailability {
    return { status: "not-implemented", message: "GitHub pull-request review will use VS Code Authentication/OAuth after its API contract and tests are implemented.", requiresUserAction: true };
  }

  async authenticateAfterUserAction(): Promise<GitHubAuthenticationState> {
    const session = await vscode.authentication.getSession("github", ["repo"], { createIfNone: true });
    return session ? { authenticated: true, accountLabel: session.account.label, message: "GitHub access is ready for a future pull-request review. No API request was made." } : { authenticated: false, message: "GitHub sign-in was cancelled. No API request was made." };
  }
}
