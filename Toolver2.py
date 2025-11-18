import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import subprocess
import threading
import sys
import os
import re
import time # Cần cho việc thêm delay tránh Rate Limit

# --- YÊU CẦU THƯ VIỆN GOOGLE API (CHỈ DÀNH CHO TAB UPLOAD) ---
try:
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    import pickle
except ImportError:
    # Nếu không có Google API, vẫn cho phép chạy Download
    pass

# --- CẤU HÌNH CHUNG ---
CONCURRENT_FRAGMENTS = 5 # Số luồng tăng tốc tải xuống
SCOPES = ['https://www.googleapis.com/auth/youtube']
CLIENT_SECRETS_FILE = 'client_secrets.json' 
TOKEN_FILE = 'token.pickle'

# --- TÊN FILE COOKIE MẶC ĐỊNH ---
COOKIE_YT_FILE = 'Cookies-yt.txt'
COOKIE_FB_FILE = 'Cookies-fb.txt'

# -----------------------------------------------
# --- HÀM HỖ TRỢ CHUNG ---
# -----------------------------------------------

def update_log_safe(log_widget, message):
    """Cập nhật log an toàn từ bất kỳ luồng nào."""
    log_widget.after(0, lambda: [
        log_widget.insert(tk.END, message + "\n"),
        log_widget.see(tk.END) 
    ])

def update_result_widget(result_widget, message, clear=False):
    """Cập nhật khu vực hiển thị kết quả cuối cùng (link)"""
    result_widget.after(0, lambda: [
        result_widget.config(state=tk.NORMAL),
        result_widget.delete("1.0", tk.END) if clear else None,
        result_widget.insert(tk.END, message + "\n"),
        result_widget.config(state=tk.DISABLED)
    ])

def browse_files(video_paths_listbox):
    """Mở hộp thoại cho phép chọn nhiều file video."""
    filenames = filedialog.askopenfilenames(
        title="Chọn các File Video để tải lên",
        filetypes=[("Video files", "*.mp4 *.mov *.avi"), ("All files", "*.*")]
    )
    if filenames:
        video_paths_listbox.delete(0, tk.END)
        for f in filenames:
            video_paths_listbox.insert(tk.END, f)

# -----------------------------------------------
# --- CHỨC NĂNG TẢI LÊN YOUTUBE (UPLOAD) ---
# -----------------------------------------------

def get_authenticated_service(log_widget):
    """Xác thực người dùng bằng OAuth 2.0."""
    credentials = None
    
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'rb') as token:
            credentials = pickle.load(token)

    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            try:
                credentials.refresh(Request())
            except Exception:
                update_log_safe(log_widget, "❌ Lỗi: Không thể refresh token. Vui lòng xóa token.pickle và xác thực lại.")
                credentials = None
            
        if not credentials:
            if not os.path.exists(CLIENT_SECRETS_FILE):
                update_log_safe(log_widget, f"❌ Lỗi File: Không tìm thấy '{CLIENT_SECRETS_FILE}'.")
                messagebox.showerror("Lỗi File", f"Không tìm thấy file xác thực '{CLIENT_SECRETS_FILE}'.")
                return None
            
            try:
                from google_auth_oauthlib.flow import InstalledAppFlow
                flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)
                credentials = flow.run_local_server(port=0) 
            except Exception as e:
                update_log_safe(log_widget, f"❌ Lỗi OAuth: {e}")
                return None

        with open(TOKEN_FILE, 'wb') as token:
            pickle.dump(credentials, token)

    return build('youtube', 'v3', credentials=credentials)

def create_youtube_playlist(youtube, title, privacy_status, log_widget):
    """Tạo một Playlist mới trên YouTube và trả về ID."""
    update_log_safe(log_widget, f"4. Đang tạo Playlist: '{title}'...")
    
    request_body = {
        'snippet': {'title': title, 'description': f"Playlist tự động tạo bởi YouTube Automation Tool. Chế độ: {privacy_status}."},
        'status': {'privacyStatus': privacy_status}
    }
    
    try:
        response = youtube.playlists().insert(part='snippet,status', body=request_body).execute()
        playlist_id = response['id']
        update_log_safe(log_widget, f"✅ Tạo Playlist thành công. ID: {playlist_id}")
        return playlist_id
    except Exception as e:
        update_log_safe(log_widget, f"❌ Lỗi khi tạo Playlist: {e}")
        return None

def add_video_to_playlist(youtube, video_id, playlist_id, log_widget):
    """Thêm video đã upload vào Playlist đã chỉ định."""
    try:
        youtube.playlistItems().insert(
            part='snippet',
            body={'snippet': {'playlistId': playlist_id, 'resourceId': {'kind': 'youtube#video', 'videoId': video_id}}}
        ).execute()
        return True
    except Exception as e:
        update_log_safe(log_widget, f"Lỗi khi thêm video {video_id} vào playlist {playlist_id}: {e}")
        return False

def upload_video_and_add_to_playlist(video_path: str, title: str, description: str, privacy: str, playlist_id: str, log_widget: tk.Text, result_widget: tk.Text):
    
    update_log_safe(log_widget, f"\n--- BẮT ĐẦU TẢI LÊN FILE: {os.path.basename(video_path)} ---")
    
    youtube = get_authenticated_service(log_widget)
    if not youtube: return

    body = {
        'snippet': {'title': title, 'description': description, 'categoryId': '22'},
        'status': {'privacyStatus': privacy}
    }
    media = MediaFileUpload(video_path, chunksize=-1, resumable=True)

    try:
        update_log_safe(log_widget, "3. Đang tải file lên...")
        
        request = youtube.videos().insert(part='snippet,status', body=body, media_body=media)
        
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                if status.progress() > 0.99 or status.progress() == 0.0:
                    update_log_safe(log_widget, f"    Đã tải lên {int(status.progress() * 100)}%")

        if response is not None:
            video_id = response['id']
            video_url = f"https://youtu.be/{video_id}"
            update_log_safe(log_widget, f"✅ Tải lên THÀNH CÔNG: {os.path.basename(video_path)}")
            
            if playlist_id:
                if youtube and add_video_to_playlist(youtube, video_id, playlist_id, log_widget):
                    update_log_safe(log_widget, f"    ➡️ Đã thêm vào Playlist: {playlist_id}")

            update_log_safe(log_widget, f"🔗 Link: {video_url}")
            
            result_entry = f"Video: {title} -> {video_url}"
            result_widget.after(0, lambda: [
                result_widget.config(state=tk.NORMAL),
                result_widget.insert(tk.END, result_entry + "\n"),
                result_widget.config(state=tk.DISABLED)
            ])

    except Exception as e:
        update_log_safe(log_widget, f"❌ Lỗi khi tải lên file {os.path.basename(video_path)}: {e}")

def start_upload_thread_handler(video_paths_listbox, description_text, privacy_var, playlist_name_entry, upload_log_text, result_widget):
    
    paths = video_paths_listbox.get(0, tk.END)
    
    if not paths:
        messagebox.showerror("Lỗi", "Vui lòng chọn ít nhất một File Video.")
        return
        
    desc = description_text.get("1.0", tk.END).strip()
    privacy = privacy_var.get()

    upload_log_text.delete("1.0", tk.END)
    upload_log_text.insert(tk.END, f"Chuẩn bị tải lên hàng loạt {len(paths)} video...\n")
    
    threads = []
    playlist_name = playlist_name_entry.get().strip()
    playlist_id = None
    
    # BƯỚC 1: XỬ LÝ TẠO PLAYLIST (NẾU CÓ)
    if playlist_name:
        youtube = get_authenticated_service(upload_log_text)
        if youtube:
            playlist_id = create_youtube_playlist(youtube, playlist_name, privacy, upload_log_text)
            if playlist_id:
                playlist_url = f"https://www.youtube.com/playlist?list={playlist_id}"
                update_result_widget(result_widget, f"Playlist được tạo:\n{playlist_name} -> {playlist_url}", clear=True)
                
                # *** CHÈN DELAY TẠI ĐÂY để tránh Rate Limit khi tạo playlist ***
                update_log_safe(upload_log_text, "⏸️ Tạm dừng 3 giây để tránh Rate Limit...")
                time.sleep(3) 
                # *************************************************************
    else:
        update_result_widget(result_widget, "", clear=True)

    # BƯỚC 2: TẢI VIDEO HÀNG LOẠT
    for path in paths:
        if not os.path.exists(path):
            update_log_safe(upload_log_text, f"❌ Bỏ qua: File không tồn tại tại {path}")
            continue

        filename_with_ext = os.path.basename(path) 
        filename_without_ext, _ = os.path.splitext(filename_with_ext)
        title = filename_without_ext 
        
        # Kiểm tra và làm sạch Tiêu đề
        MAX_TITLE_LENGTH = 90  
        title = re.sub(r'[^\w\s.,\-()\[\]]+', '', title) 
        
        if len(title) > MAX_TITLE_LENGTH:
            title = title[:MAX_TITLE_LENGTH] + '...'
        
        if not title.strip():
            title = f"Uploaded Video ({os.path.basename(path)})"
            
        thread = threading.Thread(
            target=upload_video_and_add_to_playlist,
            args=(path, title, desc, privacy, playlist_id, upload_log_text, result_widget)
        )
        threads.append(thread)
        thread.start()

    # Tạo luồng giám sát để thông báo khi tất cả hoàn tất
    def check_upload_completion():
        if all(not t.is_alive() for t in threads):
            upload_log_text.after(0, lambda: [
                upload_log_text.insert(tk.END, "\n--- HOÀN TẤT TẤT CẢ TÁC VỤ TẢI LÊN ---\n"),
                messagebox.showinfo("Hoàn tất Tải Lên", f"Đã hoàn thành tải lên {len(paths)} video!")
            ])
        else:
            upload_log_text.after(500, check_upload_completion)

    upload_log_text.after(500, check_upload_completion)

# -----------------------------------------------
# --- CHỨC NĂNG TẢI XUỐNG CHUNG (DOWNLOAD CORE) ---
# -----------------------------------------------

def download_single_url(url: str, url_type: str, format_choice: str, name_format: str, output_dir: str, download_playlist: bool, log_text_widget: tk.Text):
    
    def update_log(message):
        update_log_safe(log_text_widget, message)

    update_log(f"\n🚀 Bắt đầu tải URL: {url}...")
    
    # 1. Xác định file cookies
    cookie_file_path = COOKIE_FB_FILE if url_type == 'facebook' else COOKIE_YT_FILE
    
    cookie_options = []
    if os.path.exists(cookie_file_path):
        cookie_options = ["--cookies", cookie_file_path] # Sử dụng --cookies thay vì -c
        update_log(f"-> Đang sử dụng file cookie: '{cookie_file_path}'")
    else:
        update_log(f"⚠️ CẢNH BÁO: Không tìm thấy file cookie '{cookie_file_path}'. Video riêng tư có thể không tải được.")
    
    # 2. Xây dựng lệnh yt-dlp
    try:
        command = [
            sys.executable, "-m", "yt_dlp",
        ] + cookie_options + [ 
            
            "--no-warnings", 
            "--no-abort-on-error",
            
            "--no-mtime",
            "--restrict-filenames",
            "--paths", output_dir,
            "-o", name_format 
        ]
        
        # 3. Thêm tùy chọn Playlist
        if download_playlist: command.append("--yes-playlist")
        else: command.append("--no-playlist")

        # 4. Thêm tùy chọn chất lượng
        if format_choice == "video":
            command.append("--concurrent-fragments")
            command.append(str(CONCURRENT_FRAGMENTS))
            command.append("-f")
            command.append("bestvideo[ext=mp4]+bestaudio[ext=m4a]/best")
            update_log(f"  - Định dạng: Video chất lượng cao (tăng tốc x{CONCURRENT_FRAGMENTS} luồng)...")
            
        elif format_choice == "mp3":
            command.append("--extract-audio")
            command.append("--audio-format")
            command.append("mp3")
            command.append("--audio-quality")
            command.append("0")
            update_log("  - Định dạng: Chỉ tải Audio (MP3)...")

        # 5. Thêm URL cuối cùng
        command.append(url)
        
        # Thực thi lệnh
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, universal_newlines=True)
        
        output_lines = []
        for line in process.stdout:
            update_log(line.strip())
            output_lines.append(line.strip())
        
        process.wait()
        
        # 6. LOGIC XỬ LÝ KẾT QUẢ (Kiểm tra gộp file/đã tải thành công)
        download_success = any("[Merger] Merging formats into" in line for line in output_lines) or any("has already been downloaded" in line for line in output_lines)
        
        if process.returncode == 0 or download_success:
            update_log(f"✅ Tải thành công URL: {url}")
        else:
            update_log(f"❌ Lỗi nghiêm trọng khi tải URL: {url} (Mã lỗi: {process.returncode})")

    except FileNotFoundError:
        update_log("❌ Lỗi: 'yt-dlp' chưa được cài đặt. Vui lòng chạy 'pip install yt-dlp'.")
    except Exception as e:
        update_log(f"❌ Lỗi không xác định khi xử lý URL {url}: {e}")
        
# -----------------------------------------------
# --- HÀM XỬ LÝ TẢI XUỐNG RIÊNG CHO TỪNG TAB ---
# -----------------------------------------------

def start_download_handler(link_text, format_var, playlist_var, name_format_entry, output_entry, log_text_widget, url_type):
    """Xử lý bắt đầu tải xuống cho YT hoặc FB."""
    links_input = link_text.get("1.0", tk.END).strip()
    if not links_input:
        messagebox.showerror("Lỗi", "Vui lòng nhập ít nhất một link.")
        return
        
    # --- LỌC URL DỰA TRÊN LOẠI (url_type) ---
    if url_type == 'youtube':
        pattern = r'https?://(?:www\.)?(?:youtube\.com|youtu\.be)/[^\s]+'
        cookie_file_to_check = COOKIE_YT_FILE
    elif url_type == 'facebook':
        pattern = r'https?://(?:www\.)?(?:facebook\.com|fb\.watch)/[^\s]+'
        cookie_file_to_check = COOKIE_FB_FILE
    else:
        return
        
    url_pattern = re.compile(pattern, re.IGNORECASE)
    
    # 1. Lọc các URL hợp lệ
    url_list = [url.strip() for url in links_input.split('\n') if url_pattern.match(url.strip())]
    
    # 2. LỌC PHÒNG THỦ: Loại bỏ tên file cookie nếu nó bị nhập nhầm vào ô link
    url_list = [url for url in url_list if url.lower() != cookie_file_to_check.lower()]
    
    if not url_list:
        messagebox.showerror("Lỗi URL", f"Không tìm thấy URL {url_type.upper()} hợp lệ nào. Vui lòng kiểm tra lại link đã nhập.")
        return
    # ----------------
    
    format_choice = format_var.get()
    output_dir = output_entry.get().strip()
    download_playlist = playlist_var.get()
    
    # Xử lý tên file
    raw_name = name_format_entry.get().strip()
    name_format = raw_name # Lấy chuỗi format thô

    # *** CHỈNH SỬA TỰ ĐỘNG CHỌN FORMAT KHI BỎ TRỐNG ***
    if not name_format:
        name_format = "%(title)s.%(ext)s"
        log_text_widget.insert(tk.END, "📢 Tên file đang trống. Tự động dùng format: %(title)s.%(ext)s\n")
    # -------------------------------------------------------------------
    
    # *** KIỂM TRA GHI ĐÈ KHI TẢI HÀNG LOẠT ***
    if len(url_list) > 1 and not ('%' in name_format):
         messagebox.showerror("LỖI ĐẶT TÊN HÀNG LOẠT", 
                              "Không thể tải hàng loạt! Vui lòng sử dụng các biến định dạng của yt-dlp (ví dụ: %(title)s.%(ext)s) trong ô Tên File để tránh ghi đè file.")
         return
    
    if not output_dir or not name_format:
        messagebox.showerror("Lỗi", "Vui lòng nhập thư mục lưu trữ và định dạng/tên file.")
        return
        
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    log_text_widget.delete("1.0", tk.END)
    log_text_widget.insert(tk.END, f"Chuẩn bị tải {len(url_list)} URL {url_type.upper()}...\n")
    
    threads = []
    
    for url in url_list:
        download_thread = threading.Thread(
            target=download_single_url, 
            args=(url, url_type, format_choice, name_format, output_dir, download_playlist, log_text_widget)
        )
        threads.append(download_thread)
        download_thread.start()

    def check_threads_completion():
        if all(not t.is_alive() for t in threads):
            log_text_widget.after(0, lambda: [
                log_text_widget.insert(tk.END, "\n--- HOÀN TẤT TẤT CẢ TÁC VỤ TẢI XUỐNG ---\n"),
                messagebox.showinfo("Hoàn tất Tải Xuống", "Quá trình tải xuống đã hoàn thành!")
            ])
        else:
            log_text_widget.after(500, check_threads_completion)

    log_text_widget.after(500, check_threads_completion)


def start_yt_download_handler(link_text, format_var, playlist_var, name_format_entry, output_entry, log_text_widget):
    start_download_handler(link_text, format_var, playlist_var, name_format_entry, output_entry, log_text_widget, 'youtube')

def start_fb_download_handler(link_text, format_var, playlist_var, name_format_entry, output_entry, log_text_widget):
    start_download_handler(link_text, format_var, playlist_var, name_format_entry, output_entry, log_text_widget, 'facebook')

# -----------------------------------------------
# --- THIẾT LẬP GIAO DIỆN TKINTER ---
# -----------------------------------------------

def create_download_frame(notebook, title, url_type, cookie_file):
    """Tạo một frame chung cho tab Tải xuống (YouTube/Facebook)."""
    frame = ttk.Frame(notebook, padding="10")
    notebook.add(frame, text=title)

    # INPUT LINK
    ttk.Label(frame, text=f"🔗 Nhập Link {url_type.upper()} (Mỗi link 1 dòng):", font=('Arial', 10, 'bold')).pack(anchor='w', pady=(5, 2))
    
    # *** CHIỀU CAO 3 DÒNG ***
    link_text = tk.Text(frame, height=3, wrap=tk.WORD, font=('Arial', 10))
    link_text.pack(fill='x', padx=5, pady=5)
    # --------------------------
    
    # TÙY CHỌN CHUNG
    options_frame = ttk.Frame(frame)
    options_frame.pack(fill='x', pady=10)
    
    # Thư mục lưu
    ttk.Label(options_frame, text="📂 Thư mục Lưu:", font=('Arial', 10, 'bold')).grid(row=0, column=0, sticky='w', padx=5, pady=5)
    output_entry = ttk.Entry(options_frame, width=40)
    output_entry.insert(0, f"./TaiXuong/{url_type.upper()}")
    output_entry.grid(row=0, column=1, sticky='we', padx=5, pady=5)

    # Đặt tên file
    ttk.Label(options_frame, text="🏷️ Tên File Đầu Ra:", font=('Arial', 10, 'bold')).grid(row=1, column=0, sticky='w', padx=5, pady=5)
    name_format_entry = ttk.Entry(options_frame, width=40)
    
    if url_type == 'youtube':
        name_format_entry.insert(0, "%(title)s - %(id)s.%(ext)s")
        ttk.Label(options_frame, text="*Dùng định dạng %(title)s, %(id)s, %(playlist_index)s v.v.*", foreground='gray').grid(row=2, column=1, sticky='w', padx=5, pady=0)
    else: # Facebook
        name_format_entry.insert(0, "") # Mặc định là trống
        ttk.Label(options_frame, text="*Bỏ trống sẽ tự động dùng %(title)s.%(ext)s*", foreground='gray').grid(row=2, column=1, sticky='w', padx=5, pady=0)

    name_format_entry.grid(row=1, column=1, sticky='we', padx=5, pady=5)
    
    format_var = tk.StringVar(value="video")
    playlist_var = tk.BooleanVar(value=False)
    
    # Tùy chọn chất lượng
    ttk.Label(options_frame, text="⚙️ Chất lượng:", font=('Arial', 10, 'bold')).grid(row=3, column=0, sticky='w', padx=5, pady=5)
    radio_video = ttk.Radiobutton(options_frame, text=f"Video Chất Lượng Cao (Tăng tốc x{CONCURRENT_FRAGMENTS} luồng)", variable=format_var, value="video")
    radio_video.grid(row=3, column=1, sticky='w', padx=5, pady=2)
    radio_mp3 = ttk.Radiobutton(options_frame, text="Chỉ Audio (MP3 Chất Lượng Cao)", variable=format_var, value="mp3")
    radio_mp3.grid(row=4, column=1, sticky='w', padx=5, pady=2)
    
    # Tùy chọn Playlist
    check_playlist = ttk.Checkbutton(options_frame, text="Tải toàn bộ Playlist/Album", variable=playlist_var)
    check_playlist.grid(row=5, column=1, sticky='w', padx=5, pady=5)
    
    # Thông tin Cookie
    ttk.Label(options_frame, text="🔒 Cookie File:", font=('Arial', 10, 'bold')).grid(row=6, column=0, sticky='w', padx=5, pady=5)
    ttk.Label(options_frame, text=f"{cookie_file} (Cần cho video riêng tư)", foreground='red').grid(row=6, column=1, sticky='w', padx=5, pady=5)

    options_frame.grid_columnconfigure(1, weight=1)
    
    # NÚT VÀ LOG
    download_log_text = tk.Text(frame, height=12, wrap=tk.WORD, bg='#f0f0f0', font=('Courier', 9))
    
    if url_type == 'youtube':
        command_func = lambda: start_yt_download_handler(link_text, format_var, playlist_var, name_format_entry, output_entry, download_log_text)
    else:
        command_func = lambda: start_fb_download_handler(link_text, format_var, playlist_var, name_format_entry, output_entry, download_log_text)
        
    download_button = ttk.Button(frame, text="⬇️ Bắt Đầu Tải Xuống", command=command_func)
    download_button.pack(fill='x', pady=10, padx=5)
    
    ttk.Label(frame, text="📝 Log Trạng Thái Tải Xuống:", font=('Arial', 10, 'bold')).pack(anchor='w', pady=(5, 2))
    download_log_text.pack(fill='both', expand=True, padx=5, pady=5)
    
    return frame


def create_gui():
    root = tk.Tk()
    root.title("YouTube/Facebook Automation Tool (3 Tabs)")
    root.geometry("700x780")

    notebook = ttk.Notebook(root)
    notebook.pack(pady=10, padx=10, fill='both', expand=True)

    # --- Tab 1: DOWNLOAD YOUTUBE ---
    create_download_frame(notebook, '⬇️ Tải Xuống YouTube', 'youtube', COOKIE_YT_FILE)
    
    # --- Tab 2: DOWNLOAD FACEBOOK ---
    create_download_frame(notebook, '⬇️ Tải Xuống Facebook', 'facebook', COOKIE_FB_FILE)
    
    # --- Tab 3: UPLOAD YOUTUBE ---
    upload_frame = ttk.Frame(notebook, padding="10")
    notebook.add(upload_frame, text='⬆️ Tải Lên YouTube (Hàng Loạt)')
    
    # UPLOAD: INPUTS
    upload_inputs_frame = ttk.Frame(upload_frame)
    upload_inputs_frame.pack(fill='x', pady=10)
    
    # File Video (Listbox)
    ttk.Label(upload_inputs_frame, text="📹 File Video (Hàng Loạt):", font=('Arial', 10, 'bold')).grid(row=0, column=0, sticky='nw', padx=5, pady=5)
    video_paths_listbox = tk.Listbox(upload_inputs_frame, height=5, width=50) 
    video_paths_listbox.grid(row=0, column=1, sticky='we', padx=5, pady=5)
    
    ttk.Button(upload_inputs_frame, text="Chọn Files", command=lambda: browse_files(video_paths_listbox)).grid(row=0, column=2, padx=5, pady=5)

    # Tiêu đề (Tự động lấy)
    ttk.Label(upload_inputs_frame, text="🏷️ Tiêu đề:", font=('Arial', 10, 'bold')).grid(row=1, column=0, sticky='w', padx=5, pady=5)
    ttk.Label(upload_inputs_frame, text="*Tự động lấy từ tên file (cho từng file)*", foreground='gray').grid(row=1, column=1, columnspan=2, sticky='w', padx=5, pady=5)
    
    # Playlist Name
    ttk.Label(upload_inputs_frame, text="▶️ Tên Playlist (Tùy chọn):", font=('Arial', 10, 'bold')).grid(row=2, column=0, sticky='w', padx=5, pady=5)
    playlist_name_entry = ttk.Entry(upload_inputs_frame, width=40)
    playlist_name_entry.grid(row=2, column=1, columnspan=2, sticky='we', padx=5, pady=5)
    
    # Chế độ riêng tư
    ttk.Label(upload_inputs_frame, text="🔒 Chế độ:", font=('Arial', 10, 'bold')).grid(row=3, column=0, sticky='w', padx=5, pady=5)
    privacy_var = tk.StringVar(value="unlisted")
    privacy_options = [('Không công khai', 'unlisted'), ('Công khai', 'public'), ('Riêng tư', 'private')]
    
    privacy_radio_frame = ttk.Frame(upload_inputs_frame)
    for i, (text, value) in enumerate(privacy_options):
        ttk.Radiobutton(privacy_radio_frame, text=text, variable=privacy_var, value=value).pack(side='left', padx=10)
    privacy_radio_frame.grid(row=3, column=1, columnspan=2, sticky='w', padx=5, pady=5)

    # Mô tả (Áp dụng chung)
    ttk.Label(upload_inputs_frame, text="📝 Mô tả:", font=('Arial', 10, 'bold')).grid(row=4, column=0, sticky='w', padx=5, pady=5)
    description_text = tk.Text(upload_inputs_frame, height=5, wrap=tk.WORD, font=('Arial', 10))
    description_text.grid(row=4, column=1, columnspan=2, sticky='we', padx=5, pady=5)

    upload_inputs_frame.grid_columnconfigure(1, weight=1)

    # UPLOAD: NÚT VÀ LOG
    upload_log_text = tk.Text(upload_frame, height=15, wrap=tk.WORD, bg='#f0f0f0', font=('Courier', 9))
    
    # KHU VỰC KẾT QUẢ
    result_text_widget = tk.Text(upload_frame, height=8, wrap=tk.WORD, bg='#e0f7fa', font=('Courier', 9), state=tk.DISABLED)
    
    ttk.Button(upload_frame, text="⬆️ Tải Lên YouTube", 
               command=lambda: start_upload_thread_handler(video_paths_listbox, description_text, privacy_var, playlist_name_entry, upload_log_text, result_text_widget)).pack(fill='x', pady=10, padx=5)

    # UPLOAD: LOG TRẠẠNG THÁI
    ttk.Label(upload_frame, text="📝 Log Trạng Thái Tải Lên:", font=('Arial', 10, 'bold')).pack(anchor='w', pady=(5, 2))
    upload_log_text.pack(fill='both', expand=True, padx=5, pady=5)
    
    # UPLOAD: KHU VỰC KẾT QUẢ VÀ LINK COPY
    ttk.Label(upload_frame, text="🔗 Kết Quả Upload (Link & Tiêu đề):", font=('Arial', 10, 'bold')).pack(anchor='w', pady=(10, 2))
    result_text_widget.pack(fill='x', padx=5, pady=5)
    
    root.mainloop()

# --- CHẠY CHƯƠNG TRÌNH ---
if __name__ == "__main__":
    create_gui()