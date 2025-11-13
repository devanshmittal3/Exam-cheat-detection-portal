from flask import Flask, render_template, Response, request, jsonify, redirect, url_for
from camera import VideoCamera
import time
import threading

app = Flask(__name__)

# --- MOCK DATABASE (GLOBAL STATE) ---
EXAMS = {
    "exam_001": [
        {"id": 1, "text": "What is the capital of France?", "options": {"A": "Berlin", "B": "Paris", "C": "Rome"}, "answer": "B"},
        {"id": 2, "text": "What does SQL stand for?", "options": {"A": "Structured Query Language", "B": "Standard Question Language", "C": "Simple Query Logic"}, "answer": "A"},
        {"id": 3, "text": "Who painted the Mona Lisa?", "options": {"A": "Van Gogh", "B": "Da Vinci", "C": "Picasso"}, "answer": "B"},
    ]
}

USERS = {
    "student_101": {"name": "Alice Smith", "exam_id": "exam_001", "current_q_index": 0, "status": "active", "submitted": False, "score": 0, "answers": {}}
}

# --- CENTRAL LOGGING SYSTEM ---
SESSION_LOGS = {}
STUDENT_ID = "student_101" # Fixed ID for this PoC
SESSION_LOGS[STUDENT_ID] = {"video_warnings": [], "browser_events": [], "admin_actions": []}

def central_log_handler(student_id, log_type, level, message):
    """Function to centralize all logging from various sources."""
    timestamp = time.strftime('%H:%M:%S')
    log_entry = {
        "time": timestamp,
        "type": log_type,     
        "level": level,      
        "message": message
    }
    
    if student_id in SESSION_LOGS:
        if log_type == 'video':
            SESSION_LOGS[student_id]['video_warnings'].append(log_entry)
        elif log_type == 'browser':
            SESSION_LOGS[student_id]['browser_events'].append(log_entry)
        elif log_type == 'admin':
            SESSION_LOGS[student_id]['admin_actions'].append(log_entry)

    
    print(f"[{timestamp}][{log_type.upper()}][{level}] Student {student_id}: {message}")


# --- Flask Routes ---

# 1. Student Exam Page (Dynamic Content)
@app.route('/')
def index():
    user = USERS.get(STUDENT_ID)
    if not user:
        return "User not found.", 404
    if user['submitted']:
        return render_template('results.html', user=user)

    # The student view now uses JavaScript to load the first question.
    return render_template('index.html', student_id=STUDENT_ID, total_questions=len(EXAMS[user['exam_id']]))

# 2. API to get the current question
@app.route('/api/get_question/<student_id>')
def get_question(student_id):
    user = USERS.get(student_id)
    if not user or user['submitted']:
        return jsonify({"error": "Exam ended or user not found"}), 404
        
    exam = EXAMS.get(user['exam_id'])
    q_index = user['current_q_index']
    
    if q_index >= len(exam):
        return jsonify({"finished": True, "message": "All questions answered."})

    question_data = exam[q_index]
    # Do not send the correct answer to the client!
    data_to_send = {k: v for k, v in question_data.items() if k != 'answer'}
    data_to_send['q_number'] = q_index + 1
    
    return jsonify(data_to_send)

# 3. API to submit an answer and move to the next question
@app.route('/api/submit_answer/<student_id>', methods=['POST'])
def submit_answer(student_id):
    data = request.json
    user = USERS.get(student_id)
    
    if not user or user['submitted']:
        return jsonify({"error": "Exam ended or user not found"}), 400
        
    exam = EXAMS.get(user['exam_id'])
    q_index = user['current_q_index']
    
    if q_index >= len(exam):
        return jsonify({"error": "No more questions"}), 400
        
    # Process Answer
    current_q = exam[q_index]
    selected_option = data.get('selected_option')
    
    user['answers'][current_q['id']] = selected_option
    
    # Check if correct (for simple scoring)
    is_correct = (selected_option == current_q['answer'])
    if is_correct:
        user['score'] += 1
        
    # Move to next question
    user['current_q_index'] += 1
    
    # Check for exam submission
    if user['current_q_index'] >= len(exam):
        user['submitted'] = True
        central_log_handler(student_id, 'system', 'INFO', f"Exam submitted automatically. Score: {user['score']}/{len(exam)}")
        return jsonify({"success": True, "finished": True})

    central_log_handler(student_id, 'system', 'INFO', f"Answer submitted for Q{q_index+1}. Next question loaded.")
    return jsonify({"success": True, "finished": False})


# 4. Admin Action: Send Warning
@app.route('/api/admin/send_warning/<student_id>', methods=['POST'])
def admin_send_warning(student_id):
    message = request.json.get('message', 'General warning sent by proctor.')
    
    central_log_handler(student_id, 'admin', 'WARNING', f"Proctor sent warning: {message}")
    # In a real app, this would use WebSockets to send a popup to the student
    
    return jsonify({"success": True, "message": "Warning logged and sent (conceptually)."}), 200

# 5. Admin Action: End Session
@app.route('/api/admin/end_session/<student_id>', methods=['POST'])
def admin_end_session(student_id):
    user = USERS.get(student_id)
    if user:
        user['status'] = 'force_ended'
        user['submitted'] = True # Force submission/end
        central_log_handler(student_id, 'admin', 'CRITICAL', "Proctor FORCEFULLY ENDED the session.")
        return jsonify({"success": True, "message": "Session force-ended."}), 200
    
    return jsonify({"success": False, "message": "User not found."}), 404


# --- Existing Routes (No Change Needed) ---
@app.route('/video_feed/<student_id>')
def video_feed(student_id):
    # ... (code for video_feed remains the same, initializing VideoCamera) ...
    if student_id == STUDENT_ID:
        cam = VideoCamera()
        cam.initialize(student_id, central_log_handler) 
        
        return Response(gen(cam),
                        mimetype='multipart/x-mixed-replace; boundary=frame')
    return "Error: Student not found", 404

def gen(camera):
    # ... (code for gen remains the same) ...
    while True:
        frame = camera.get_frame() 
        if frame:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

@app.route('/admin')
def admin():
    # ... (code for admin remains the same) ...
    data = {
        "student_id": STUDENT_ID,
    }
    return render_template('admin.html', student_data=data)

@app.route('/get_latest_logs/<student_id>')
def get_latest_logs(student_id):
    # ... (code for get_latest_logs remains the same) ...
    if student_id in SESSION_LOGS:
        return jsonify(SESSION_LOGS[student_id])
    return jsonify({"error": "Student not found"}), 404

@app.route('/log_browser_event', methods=['POST'])
def log_browser_event():
    # ... (code for log_browser_event remains the same) ...
    data = request.json
    student_id = data.get('student_id')
    event_type = data.get('event_type')
    details = data.get('details', '')
    
    if student_id in SESSION_LOGS:
        level = "CRITICAL" if event_type in ["tab_switch", "copy", "paste"] else "WARNING"
        central_log_handler(student_id, 'browser', level, f"Event: {event_type.upper()}. Details: {details}")
        return jsonify({"status": "logged"}), 200
    
    return jsonify({"status": "error", "message": "Invalid student ID"}), 400

if __name__ == '__main__':
    app.run(host='127.0.0.1', debug=True, threaded=True)