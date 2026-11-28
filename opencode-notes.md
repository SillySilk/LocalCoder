# Notes for this computer

## Shell
- The shell is Windows PowerShell 5.1, not bash.
- `curl` and `wget` here are PowerShell's Invoke-WebRequest and do not take curl flags. Type `curl.exe` for real curl.
- No `&&` or `||` between commands; use `;` or `if ($?) { ... }`.

## Downloading from websites
- To collect pictures of a person, character, object or style, use the bow-images `image_download` tool
  (one call per subject) rather than hand-written download scripts. It searches four image engines and skips
  small images, error pages, duplicates and pictures that do not match the search (every picture is checked,
  ~15 s each, so a 25-picture run can take 10-20 minutes; wait for it rather than retrying).
- Identify yourself honestly with a descriptive User-Agent, e.g.
  `curl.exe -L -A "GeorgeDownloader/1.0 (personal project)" -o out.jpg URL`.
  Do not pretend to be a browser ("Mozilla/5.0"): many sites, Wikimedia included, block that from scripts.
- On HTTP 429 (too many requests) or 403, waiting longer and retrying the same request rarely helps.
  Change what you send (User-Agent, an official API, a smaller batch), or move to another source.
- Wikimedia: get file URLs from the API
  (`https://commons.wikimedia.org/w/api.php?action=query&prop=imageinfo&iiprop=url&format=json&titles=File:NAME`),
  then download them one at a time, a few seconds apart.
- If webfetch gets 403/blocked or an empty page, read it with the firecrawl scrape tool instead.
- After downloading, check each file is really an image (size, and not starting with `<!DOCTYPE`/`<html`);
  an error page saved under a .jpg name is a failed download.
- If the same approach has failed twice, stop and try a different approach rather than a variation of it.
