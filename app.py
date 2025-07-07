# --- Imports ---
from flask import Flask, render_template, send_file, redirect, request, session, url_for, flash, jsonify
import os
import json
import base64
import string
import fitz  # PyMuPDF
import random
from mistralai import Mistral
import mysql.connector
import requests
import shutil
from datetime import timedelta
import googleapiclient.discovery
import googleapiclient.errors

app = Flask(__name__)
app.secret_key = "Qazwsx@123"

# Database connection
try:
    link = mysql.connector.connect(
        host='localhost',
        user='root',
        password='',
        database='skillgap_2025'
    )
    print("Database connection successful")
except mysql.connector.Error as err:
    print(f"FATAL: Error connecting to database: {err}")
    print("Authentication features will fail. Please check DB connection details and ensure MySQL is running.")
    link = None

# Mistral AI setup
mistral_api_key = "WTuMOibXWmpTqjvscYHSaaCOjjXCakkJ"
mistral_model = "pixtral-large-2411"
try:
    client = Mistral(api_key=mistral_api_key)
    print("Mistral client initialized")
except Exception as e:
    print(f"FATAL: Error initializing Mistral client: {e}")
    client = None

# Adzuna API credentials
ADZUNA_APP_ID = "b03f76e8"
ADZUNA_APP_KEY = "3aba17aaa08c6bd408d4f71350fa835a"

# YouTube API setup
YOUTUBE_API_KEY = "AIzaSyCWQ5BsUYN7IG2wreRvDt5L8KEwmPbY9vQ"
try:
    youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    print("YouTube API client initialized")
except Exception as e:
    print(f"FATAL: Error initializing YouTube client: {e}")
    youtube = None

@app.after_request
def add_header(response):
    """Add headers to prevent caching."""
    response.cache_control.no_store = True
    return response

def encode_image(image_filepath):
    """Reads an image file and returns its Base64 encoded string."""
    try:
        with open(image_filepath, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        print(f"Error encoding image {image_filepath}: {e}")
        return None

def pdf_to_images(pdf_filepath, output_folder):
    """Converts each page of a PDF to a PNG image."""
    output_images = []
    try:
        doc = fitz.open(pdf_filepath)
        pdf_basename = os.path.splitext(os.path.basename(pdf_filepath))[0]
        zoom = 2
        mat = fitz.Matrix(zoom, zoom)
        print(f"Processing PDF: {os.path.basename(pdf_filepath)}, Pages: {len(doc)}")
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            pix = page.get_pixmap(matrix=mat)
            image_filename = f"page_{page_num+1}.png"
            image_filepath = os.path.join(output_folder, image_filename)
            pix.save(image_filepath)
            output_images.append(image_filepath)
        doc.close()
        print(f"Converted PDF to {len(output_images)} images in {output_folder}")
    except Exception as e:
        print(f"Error converting PDF {pdf_filepath} to images: {e}")
    return output_images

def extract_keywords_from_image(image_filepath):
    """Uses Mistral API to extract skills/keywords from a resume image."""
    if not client:
        print("Mistral client not initialized. Cannot extract keywords.")
        return []

    image_base64 = encode_image(image_filepath)
    if not image_base64:
        return []

    prompt = (
        "Analyze this resume image. Extract key skills, technologies, programming languages, frameworks, "
        "and potential job titles mentioned. Return ONLY a JSON object with a single key 'keywords' "
        "containing a list of strings. Only include relevant terms for job searching. "
        "Example: {\"keywords\": [\"Python\", \"Java\", \"SQL\", \"Data Analysis\", \"Software Engineer\", \"AWS\", \"Project Management\"]}"
    )
    messages = [{"role": "user","content": [{"type": "text", "text": prompt},{"type": "image_url", "image_url": f"data:image/png;base64,{image_base64}"}]}]

    try:
        chat_response = client.chat.complete(
            model=mistral_model,
            messages=messages,
            response_format={"type": "json_object"}
        )
        extracted_text = chat_response.choices[0].message.content

        try:
            result = json.loads(extracted_text)
            keywords = result.get("keywords", [])
            if isinstance(keywords, list):
                return keywords
            else:
                print(f"Warning: 'keywords' field in Mistral response is not a list for {os.path.basename(image_filepath)}.")
                return []
        except json.JSONDecodeError as json_e:
            print(f"Warning: Could not directly parse keyword JSON for {os.path.basename(image_filepath)}. Trying manual extraction. Error: {json_e}")
            try:
                data_start = extracted_text.find("{")
                data_end = extracted_text.rfind("}") + 1
                if data_start != -1 and data_end != -1:
                    json_data_str = extracted_text[data_start:data_end]
                    result = json.loads(json_data_str)
                    keywords = result.get("keywords", [])
                    if isinstance(keywords, list):
                        return keywords
                    else: return []
                else: return []
            except Exception as fallback_e:
                print(f"Fallback JSON extraction failed for keywords: {fallback_e}")
                return []
        except Exception as e:
            print(f"Error processing Mistral keyword response content: {e}")
            return []
    except Exception as e:
        print(f"Error during Mistral API call for keywords on {image_filepath}: {e}")
        return []

def analyze_skill_gap(resume_skills, job_title):
    """Uses Mistral to analyze the skill gap between resume and job title."""
    if not client:
        print("Mistral client not initialized. Cannot analyze skill gap.")
        return {"missing_skills": [], "analysis": ""}

    prompt = (
        f"Analyze the skill gap between these resume skills: {resume_skills} "
        f"and this target job title: {job_title}. "
        "Return a JSON object with two keys: "
        "'missing_skills' (list of skills needed for the job but not in resume), "
        "'analysis' (a brief text analysis of the gap). "
        "Example: {\"missing_skills\": [\"AWS\", \"Docker\"], \"analysis\": \"The resume lacks cloud and containerization skills...\"}"
    )

    try:
        response = client.chat.complete(
            model=mistral_model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        result = json.loads(response.choices[0].message.content)
        return result
    except Exception as e:
        print(f"Error analyzing skill gap: {e}")
        return {"missing_skills": [], "analysis": ""}

def get_youtube_tutorials(keywords, max_results=1):
    """Get YouTube tutorials for each keyword using YouTube API."""
    tutorials = {}
    if not youtube:
        print("YouTube client not initialized. Cannot fetch tutorials.")
        return tutorials
    
    for keyword in keywords:
        try:
            search_response = youtube.search().list(
                q=f"{keyword} tutorial",
                part="id,snippet",
                maxResults=max_results,
                type="video",
                order="relevance"
            ).execute()
            
            video_items = []
            for item in search_response.get("items", []):
                video_id = item["id"].get("videoId")
                video_title = item["snippet"].get("title")
                if video_id and video_title:
                    video_items.append({
                        "title": video_title,
                        "link": f"https://www.youtube.com/watch?v={video_id}"
                    })
            
            if video_items:
                tutorials[keyword] = video_items
        except googleapiclient.errors.HttpError as http_error:
            print(f"HTTP error searching YouTube for '{keyword}': {http_error}")
        except Exception as e:
            print(f"Error searching YouTube for '{keyword}': {e}")
    
    return tutorials

@app.route('/')
def index():
    if 'user' in session:
        return redirect(url_for('userhome'))
    return render_template('index.html')

@app.route('/ulogin', methods=['GET', 'POST'])
def ulogin():
    if not link or not link.is_connected():
        flash('Database connection failed. Please contact admin.', 'error')
        return render_template('ulogin.html')
    
    if 'user' in session:
        return redirect(url_for('userhome'))
    
    if request.method == "GET":
        return render_template('ulogin.html')

    cursor = None
    try:
        cursor = link.cursor(dictionary=True)
        email = request.form.get("email")
        password = request.form.get("password")

        if not email or not password:
            flash('Email and password are required.', 'warning')
            return redirect(url_for('ulogin'))

        cursor.execute("SELECT uid, name FROM skillgap_2025_user WHERE email = %s AND password = %s", (email, password))
        user = cursor.fetchone()

        if user:
            session['user'] = user['uid']
            session['username'] = user['name']
            session.permanent = True
            app.permanent_session_lifetime = timedelta(days=7)
            print(f"Login successful for user: {session['username']} ({session['user']})")
            return redirect(url_for('userhome'))
        else:
            print(f"Login failed for email: {email}")
            flash('Invalid email or password.', 'error')
            return render_template('ulogin.html')

    except mysql.connector.Error as db_err:
        print(f"Login DB error: {db_err}")
        flash('Database error during login. Please try again later.', 'error')
        return render_template('ulogin.html')
    except Exception as e:
        print(f"Login general error: {e}")
        flash('An unexpected error occurred. Please try again.', 'error')
        return render_template('ulogin.html')
    finally:
        if cursor: cursor.close()

@app.route('/uregister', methods=['GET', 'POST'])
def uregister():
    if not link or not link.is_connected():
        flash('Database connection failed. Please contact admin.', 'error')
        return render_template('uregister.html')

    if 'user' in session:
        return redirect(url_for('userhome'))

    if request.method == "GET":
        return render_template('uregister.html')

    cursor = None
    try:
        cursor = link.cursor()
        name = request.form.get("name")
        email = request.form.get("email")
        password = request.form.get("password")
        phone = request.form.get("phone")

        if not all([name, email, password, phone]):
            flash('All fields are required.', 'warning')
            return render_template('uregister.html')

        cursor.execute("SELECT email FROM skillgap_2025_user WHERE email = %s", (email,))
        if cursor.fetchone():
            print(f"Registration attempt failed: User exists {email}")
            flash('User with this email already exists. Please login or use a different email.', 'warning')
            return render_template('uregister.html')
        else:
            uid_val = 'user_' + ''.join(random.choices(string.ascii_letters + string.digits, k=10))
            insert_sql = "INSERT INTO skillgap_2025_user (uid, name, email, password, phone) VALUES (%s, %s, %s, %s, %s)"
            cursor.execute(insert_sql, (uid_val, name, email, password, phone))
            link.commit()
            print(f"Registration successful for: {name} ({email})")
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('ulogin'))

    except mysql.connector.Error as db_err:
        print(f"Registration DB error: {db_err}")
        link.rollback()
        flash('Database error during registration. Please try again.', 'error')
        return render_template('uregister.html')
    except Exception as e:
        print(f"Registration general error: {e}")
        link.rollback()
        flash('An unexpected error occurred during registration.', 'error')
        return render_template('uregister.html')
    finally:
        if cursor: cursor.close()

@app.route('/userhome', methods=['GET'])
def userhome():
    if 'user' not in session:
        flash("Please login to access your home page.", "warning")
        return redirect(url_for('ulogin'))
    return render_template('userhome.html', username=session.get('username', 'User'))

@app.route('/ulogout')
def ulogout():
    print(f"Logging out user: {session.get('username', 'N/A')} ({session.get('user', 'N/A')})")
    session.pop('user', None)
    session.pop('username', None)
    flash('You have been logged out successfully.', 'info')
    return redirect(url_for('ulogin'))

@app.route('/upload', methods=["GET", "POST"])
def upload():
    if 'user' not in session:
        flash("Please login to upload a resume.", "warning")
        return redirect(url_for('ulogin'))

    if request.method == "GET":
        return render_template('upload.html', job_results=None, video_tutorials=None, keywords_found=None, skill_gap_analysis=None)

    job_designation = request.form.get('job_designation')
    if not job_designation:
        flash("Please enter a job designation.", "error")
        return redirect(request.url)

    if 'file' not in request.files:
        flash("No file part in the request.", "error")
        return redirect(request.url)
    file = request.files['file']
    if file.filename == '':
        flash("No file selected.", "error")
        return redirect(request.url)
    if not file.filename.lower().endswith('.pdf'):
        flash("Invalid file type. Please upload a PDF file.", "error")
        return redirect(request.url)

    processing_uid = 'proc_' + ''.join(random.choices(string.ascii_letters + string.digits, k=12))
    base_folder = os.path.join("workspace", processing_uid)
    pdf_folder = os.path.join(base_folder, "pdf")
    image_folder = os.path.join(base_folder, "images")
    os.makedirs(pdf_folder, exist_ok=True)
    os.makedirs(image_folder, exist_ok=True)
    print(f"Workspace created: {base_folder}")
    
    pdf_filepath = os.path.join(pdf_folder, file.filename)
    job_results = []
    video_tutorials = {}
    final_keywords = []
    skill_gap_result = {"missing_skills": [], "analysis": ""}

    try:
        file.save(pdf_filepath)
        print(f"Saved uploaded resume: {pdf_filepath}")
        page_images = pdf_to_images(pdf_filepath, image_folder)
        if not page_images:
            raise ValueError("Failed to convert PDF to images.")

        all_keywords = set()
        if client:
            print("Extracting keywords via Mistral...")
            for img_path in page_images:
                extracted_kw = extract_keywords_from_image(img_path)
                if extracted_kw:
                    cleaned_kw = {k.strip().lower() for k in extracted_kw if k.strip() and len(k) > 1}
                    all_keywords.update(cleaned_kw)
            final_keywords = sorted(list(all_keywords))
        else:
            print("Mistral client not available. Skipping keyword extraction.")
            flash("AI client is not available, cannot extract keywords.", "warning")

        if not final_keywords and client:
            flash("Could not extract keywords from the resume. Results may be limited.", "warning")
        elif final_keywords:
            print(f"Final unique keywords extracted: {final_keywords}")

        if final_keywords and client:
            skill_gap_result = analyze_skill_gap(final_keywords, job_designation)
            print(f"Skill gap analysis result: {skill_gap_result}")

            if skill_gap_result.get('missing_skills'):
                final_keywords.extend(skill_gap_result['missing_skills'])

        if final_keywords and ADZUNA_APP_ID != "YOUR_ADZUNA_APP_ID" and ADZUNA_APP_KEY != "YOUR_ADZUNA_APP_KEY":
            location = "bengaluru"
            results_count_adzuna = 1
            k_jobs = min(len(final_keywords), 3)
            keywords_for_jobs = random.sample(final_keywords, k_jobs)

            print(f"Querying Adzuna for {len(keywords_for_jobs)} keywords: {keywords_for_jobs}...")
            for keyword in keywords_for_jobs:
                adzuna_url = (f"https://api.adzuna.com/v1/api/jobs/in/search/1?"
                           f"app_id={ADZUNA_APP_ID}&app_key={ADZUNA_APP_KEY}"
                           f"&results_per_page={results_count_adzuna}"
                           f"&what={requests.utils.quote(keyword)}"
                           f"&where={location}&content-type=application/json")
                try:
                    response = requests.get(adzuna_url, timeout=15)
                    response.raise_for_status()
                    job_data = response.json()
                    current_jobs = job_data.get('results', [])
                    if current_jobs:
                        job_results.extend(current_jobs)
                except requests.exceptions.Timeout:
                    print(f"Adzuna API request timed out for keyword '{keyword}'")
                except requests.exceptions.RequestException as req_e:
                    print(f"Adzuna API request failed for keyword '{keyword}': {req_e}")
                except json.JSONDecodeError as json_e:
                    print(f"Failed to parse Adzuna JSON for keyword '{keyword}': {json_e}")
        elif not final_keywords:
            print("Skipping Adzuna job search: No keywords extracted.")
        else:
            if final_keywords:
                print("Adzuna credentials not configured. Skipping job search.")

        print(f"Total aggregated job results found: {len(job_results)}")

        # Get YouTube tutorials for keywords
        if final_keywords:
            print(f"Fetching YouTube tutorials for {len(final_keywords)} keywords...")
            video_tutorials = get_youtube_tutorials(final_keywords, max_results=1)
            print(f"Found tutorials for {len(video_tutorials)} keywords")

        print(f"Rendering template with {len(job_results)} jobs and tutorials for {len(video_tutorials)} keywords.")

        return render_template('upload.html',
                           success='Processing successful!',
                           job_results=job_results,
                           video_tutorials=video_tutorials,
                           keywords_found=final_keywords,
                           skill_gap_analysis=skill_gap_result)

    except ValueError as ve:
        print(f"Value error during processing {processing_uid}: {ve}")
        flash(f"Processing error: {ve}", "error")
        if os.path.exists(base_folder):
            try: shutil.rmtree(base_folder)
            except Exception as cleanup_error: print(f"Error cleaning up during ValueError: {cleanup_error}")
        return redirect(url_for('upload'))
    except Exception as e:
        print(f"General error during upload processing {processing_uid}: {e}")
        if os.path.exists(base_folder):
            try: shutil.rmtree(base_folder)
            except Exception as cleanup_error: print(f"Error cleaning up during general exception: {cleanup_error}")
        flash(f"An unexpected error occurred during processing. Please try again.", "error")
        return redirect(url_for('upload'))

# [Keep all other existing routes - quiz, result, quizhistory, etc.]

if __name__ == "__main__":
    if not os.path.exists("workspace"):
        os.makedirs("workspace")
        print("Created workspace directory.")

    app.run(host='0.0.0.0', port=5000, debug=True)