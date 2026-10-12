from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import Field

from src.mcp_server.client import BackendClient
from src.utils import configure_logging, get_logger, log_extra

configure_logging("INFO")
logger = get_logger(__name__)

mcp = MCPServer(
    "nitx-poster-service",
    instructions=(
        "Tools for generating marketing posters through the Nitx poster-generation service. "
        "Poster generation is asynchronous: create_poster_job returns immediately with a job_id "
        "while the image renders in the background (typically 5-20 seconds). Poll get_job_status "
        "with that job_id every few seconds until status is 'completed' or 'failed'. Never call "
        "create_poster_job in a tight loop waiting for a result; poll get_job_status instead."
    ),
)

_client = BackendClient()


@mcp.tool()
async def list_templates(
    category: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Optional exact-match category filter, e.g. 'event', 'product', 'sale', 'social', "
                "'real_estate', 'restaurant'. Omit to list templates from every category."
            ),
        ),
    ] = None,
    search: Annotated[
        str | None,
        Field(
            default=None,
            description="Optional case-insensitive substring to match against template names.",
        ),
    ] = None,
) -> dict:
    """Browse ready-made poster templates, optionally filtered by category and/or a name search term.

    Use this before create_poster_job when the user wants to start from an existing layout.
    Returns a list of templates with id, name, and category; pass a template's id as
    template_id to create_poster_job. Returns an empty list (not an error) if nothing matches.
    """
    result = await _client.request("GET", "/templates", params={"category": category, "search": search})
    return result


@mcp.tool()
async def create_poster_job(
    product_image: Annotated[
        str,
        Field(description="URL or base64-encoded image data for the product to feature on the poster."),
    ],
    background_image: Annotated[
        str,
        Field(description="URL or base64-encoded image data for the poster background."),
    ],
    prompt: Annotated[
        str,
        Field(
            min_length=1,
            max_length=500,
            description=(
                "Natural-language description of the poster to generate (up to 500 characters). "
                "Be specific about layout, text, and style."
            ),
        ),
    ],
    image_count: Annotated[
        int,
        Field(ge=1, le=4, description="Number of poster variations to generate, between 1 and 4."),
    ],
    resolution: Annotated[
        Literal["1k", "2k"],
        Field(description="Output resolution for every generated image: '1k' or '2k'."),
    ],
    template_id: Annotated[
        str | None,
        Field(default=None, description="Optional id of a template from list_templates to base the layout on."),
    ] = None,
    idempotency_key: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Optional client-chosen key that makes retries safe. If this exact call is repeated "
                "with the same idempotency_key, the original job is returned instead of starting a "
                "second one. If omitted, a key is derived automatically from the other inputs, so an "
                "accidental retry with identical arguments is still deduplicated. Pass your own key "
                "(e.g. a UUID) only if you deliberately want two jobs with identical inputs."
            ),
        ),
    ] = None,
) -> dict:
    """Start an asynchronous poster-generation job and return immediately.

    This tool does NOT wait for the poster to finish rendering. It returns a job_id and
    status='processing' right away; jobs typically take 5-20 seconds. Call get_job_status with
    the returned job_id, waiting a few seconds between checks, until status is 'completed' or
    'failed'. If this call fails due to a network timeout, call it again with the same
    idempotency_key (or the same arguments, since a key is derived automatically) instead of
    assuming the job was never created.
    """
    body = {
        "template_id": template_id,
        "product_image": product_image,
        "background_image": background_image,
        "prompt": prompt,
        "image_count": image_count,
        "resolution": resolution,
        "idempotency_key": idempotency_key,
    }

    result = await _client.request("POST", "/jobs", json_body=body)
    logger.info("create_poster_job dispatched", extra=log_extra(job_id=result.get("job_id")))
    return result


@mcp.tool()
async def get_job_status(
    job_id: Annotated[str, Field(description="The job_id returned by create_poster_job.")],
) -> dict:
    """Check the status of a poster-generation job.

    Returns status one of 'processing', 'completed', 'failed', or 'cancelled'. When status is
    'completed', the response includes an images[] list with urls. When status is 'failed', the
    response includes an error message describing what went wrong; it is usually safe to call
    create_poster_job again to retry. If status stays 'processing' for longer than 20-30 seconds,
    keep polling every few seconds rather than assuming the job is stuck.
    """
    return await _client.request("GET", f"/jobs/{job_id}")


@mcp.tool()
async def cancel_job(
    job_id: Annotated[str, Field(description="The job_id returned by create_poster_job.")],
) -> dict:
    """Cancel a poster-generation job that is still processing.

    Returns status='cancelled' on success. Only jobs currently in 'processing' status can be
    cancelled; calling this on a job that already completed, failed, or was cancelled returns a
    clear error explaining the job's current status instead of cancelling anything.
    """
    return await _client.request("POST", f"/jobs/{job_id}/cancel")


if __name__ == "__main__":
    mcp.run()
