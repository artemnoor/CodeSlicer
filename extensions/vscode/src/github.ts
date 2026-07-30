/** P1 seam only: no network, PAT handling, or source upload lives here. */
export interface GitHubReviewAvailability { status: "not-implemented"; message: string; requiresUserAction: true }

export class GitHubReviewService {
  availability(): GitHubReviewAvailability {
    return { status: "not-implemented", message: "GitHub pull-request review will use VS Code Authentication/OAuth after its API contract and tests are implemented.", requiresUserAction: true };
  }
}
