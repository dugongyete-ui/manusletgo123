import os
from e2b import Template

def build_ai_manus_template():
    api_key = os.getenv("E2B_API_KEY")
    if not api_key:
        print("Error: E2B_API_KEY tidak ditemukan.")
        return

    print("Membangun template E2B untuk ai-manus secara murni...")
    
    os.chdir('/home/ubuntu/ai-manus/sandbox')
    
    with open('pyproject.toml', 'r') as f:
        pyproject_content = f.read().replace("'", "'\\''")
    
    with open('start.sh', 'r') as f:
        start_sh_content = f.read().replace("'", "'\\''")

    builder = (
        Template()
        .from_ubuntu_image('22.04')
        .set_workdir('/home/ubuntu/app')
        .set_envs({
            'DEBIAN_FRONTEND': 'noninteractive',
            'HOSTNAME': 'sandbox',
            'UV_INDEX_URL': 'https://mirrors.aliyun.com/pypi/simple/'
        })
        .run_cmd("sudo sed -i 's|http://archive.ubuntu.com/ubuntu/|http://mirrors.aliyun.com/ubuntu/|g' /etc/apt/sources.list")
        .run_cmd("sudo sed -i 's|http://security.ubuntu.com/ubuntu/|http://mirrors.aliyun.com/ubuntu/|g' /etc/apt/sources.list")
        .apt_install([
            'sudo', 'bc', 'curl', 'wget', 'gnupg', 'software-properties-common',
            'xvfb', 'x11vnc', 'xterm', 'socat', 'supervisor', 'websockify',
            'python3.10', 'python3.10-venv', 'python3.10-dev', 'python3-pip',
            'nodejs', 'chromium-browser', 'fonts-noto-cjk', 'fonts-noto-color-emoji',
            'language-pack-zh-hans', 'locales'
        ])
        .run_cmd('sudo update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.10 1')
        .run_cmd('sudo pip3 install uv')
        .run_cmd('sudo locale-gen zh_CN.UTF-8')
        
        .run_cmd(f"mkdir -p /home/ubuntu/app && echo '{pyproject_content}' > /home/ubuntu/app/pyproject.toml")
        .run_cmd(f"echo '{start_sh_content}' > /home/ubuntu/app/start.sh")
        .run_cmd("chmod +x /home/ubuntu/app/start.sh")
        
        .run_cmd('cd /home/ubuntu/app && uv sync --no-dev')
        # Gunakan 'true' sebagai ready_cmd agar pembangunan tidak menunggu layanan siap
        .set_start_cmd('bash /home/ubuntu/app/start.sh', 'true')
    )

    print("Membangun template di cloud E2B...")
    try:
        build_info = Template.build(
            builder,
            name='ai-manus-sandbox',
            api_key=api_key
        )
        print(f"Template berhasil dibangun! ID: {build_info.template_id}")
        return build_info.template_id
    except Exception as e:
        print(f"Gagal membangun template: {str(e)}")
        return None

if __name__ == "__main__":
    build_ai_manus_template()
