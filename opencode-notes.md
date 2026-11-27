# Notes for this computer

## Shell
- The shell is Windows PowerShell 5.1, not bash.
- `curl` and `wget` here are PowerShell's Invoke-WebRequest and do not take curl flags. Type `curl.exe` for real curl.
- No `&&` or `||` between commands; use `;` or `if ($?) { ... }`.

## Downloading from websites
- Identify yourself honestly with a descriptive User-Agent, e.g.
  `curl.exe -L -A "GeorgeDownloader/1.0 (personal project)" -o out.jpg URL`.
  Do not pretend to be a browser ("Mozilla/5.0"): many sites, Wikimedia included, block that from scripts.
- On HTTP 429 (too many requests) or 403, waiting longer and retrying the same request rarely helps.
  Change what you send (User-Agent, an official API, a smaller batch), or move to another source.
- Wikimedia: get file URLs from the API
  (`https://commons.wikimedia.org/w/api.php?action=query&prop=imageinfo&iiprop=url&format=json&titles=File:NAME`),
  then download them one at a time, a few seconds apart.
- If the same approach has failed twice, stop and try a different approach rather than a variation of it.
