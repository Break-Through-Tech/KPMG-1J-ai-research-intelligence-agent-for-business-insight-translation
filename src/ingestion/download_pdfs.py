# per paper PDF download using fetch_metadata
import os
import requests
import time

def download_pdf(short_id, pdf_url, dest_path, timeout=60):
    #if the path already exists don't download
    if os.path.exists(dest_path): 
        return "skipped_exists"

    try:
        #send GET request to the URL 
        response = requests.get(pdf_url, stream=True, timeout=timeout)
        response.raise_for_status() #throw error if there is one

        directory = os.path.dirname(dest_path)
        if directory and not os.path.exists(directory):
            os.makedirs(directory)

        with open(dest_path, 'wb') as file:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    file.write(chunk)

        print(f"Successfully downloaded: {short_id}")
        return "downloaded"
    
    except requests.exceptions.RequestException as e:
        print(f"Error downloading file: {e}")
        return "failed"

#download all papers in papers
def download_all(papers, raw_pdf_dir):
    for paper in papers:
        dest_path = os.path.join(raw_pdf_dir, f"{paper['arxiv_id']}.pdf")
        paper["pdf_path"] = dest_path
        paper["download_status"] = download_pdf(paper["arxiv_id"], paper["pdf_url"], dest_path)
        if paper["download_status"] == "downloaded":
            time.sleep(3)
    return papers