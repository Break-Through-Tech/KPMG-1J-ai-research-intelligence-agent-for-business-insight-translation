# per paper PDF download using fetch_metadata
import os
import requests
import time

def download_pdf(short_id, pdf_url, dest_path, timeout=60):
    #if the path already exists don't download
    if os.path.exists(dest_path): 
        return "skipped_exists"

    #download to a temp file and only rename it once it's complete
    #so a crash never leaves half-written PDF that later runs would skip
    tmp_path = f"{dest_path}.part"
    try:
        #send GET request to the URL 
        response = requests.get(pdf_url, stream=True, timeout=timeout)
        response.raise_for_status() #throw error if there is one

        directory = os.path.dirname(dest_path)
        if directory:
            os.makedirs(directory, exist_ok = True)

        with open(tmp_path, 'wb') as file:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    file.write(chunk)

        #arxiv sometimes returns an HTML error page with a 200 status
        with open(tmp_path, 'rb') as file:
            if file.read(5) != b"%PDF-":
                raise ValueError("response is not a PDF")

        os.replace(tmp_path, dest_path)
        print(f"Successfully downloaded: {short_id}")
        return "downloaded"
    
    except (requests.exceptions.RequestException, ValueError) as e:
        print(f"Error downloading {short_id}: {e}")
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        return "failed"

#download all papers in papers
def download_all(papers, raw_pdf_dir):
    for paper in papers:
        dest_path = os.path.join(raw_pdf_dir, f"{paper['arxiv_id']}.pdf")
        paper["pdf_path"] = dest_path
        paper["download_status"] = download_pdf(paper["arxiv_id"], paper["pdf_url"], dest_path)
        if paper["download_status"] != "skipped_exists":
            time.sleep(3) #arxiv needs 3s between requests
    return papers