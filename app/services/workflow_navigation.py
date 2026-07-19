from app.models.workflow import ResearchWorkflowRun


def automatic_workflow_destination(candidate_id: int, workflow: ResearchWorkflowRun) -> str:
    if workflow.status == "WAITING_FOR_AUTHOR_CONFIRMATION":
        return (
            f"/candidates/{candidate_id}/publications/openalex-author/confirm"
            f"?resume_workflow=1&workflow_id={workflow.id}"
        )
    if workflow.draft_id is not None:
        return f"/drafts/{workflow.draft_id}/manual-review"
    if workflow.status == "WAITING_FOR_PORTFOLIO_INPUT":
        return f"/candidates/{candidate_id}"
    if workflow.paper_file_id is not None:
        return f"/papers/{workflow.paper_file_id}"
    return f"/candidates/{candidate_id}"


def resumed_workflow_destination(candidate_id: int, workflow: ResearchWorkflowRun | None) -> str:
    if workflow is None:
        return f"/candidates/{candidate_id}"
    if workflow.draft_id is not None:
        return f"/drafts/{workflow.draft_id}/manual-review"
    if workflow.paper_file_id is not None:
        return f"/papers/{workflow.paper_file_id}"
    return f"/candidates/{candidate_id}"
