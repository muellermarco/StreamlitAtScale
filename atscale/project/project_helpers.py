import logging

from atscale.errors import atscale_errors


logger = logging.getLogger(__name__)


def _check_published(project):
    """Checks to see if there is a published version of this project

    Args:
        project (Project): The project to check
    """
    if project.published_project_name is None:
        if len(project.get_published_projects()) > 0:
            raise atscale_errors.WorkFlowError(
                "The project of the provided data_model must have an associated "
                "published project before submitting a DMV query. "
                "Try calling project.select_published_project()"
            )
        else:
            raise atscale_errors.WorkFlowError(
                "A published project is required to query against, but there is no "
                "published version of the project of the provided data_model. "
                "A project can be published programmatically by calling Project.publish()"
            )
