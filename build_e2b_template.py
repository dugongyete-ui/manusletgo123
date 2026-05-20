import os
from e2b import Template

def build_ai_manus_template():
    api_key = os.getenv("E2B_API_KEY")
    if not api_key:
        print("Error: E2B_API_KEY tidak ditemukan.")
        return

    print("Membangun template E2B untuk ai-manus secara manual...")
    
    os.chdir('/home/ubuntu/ai-manus/sandbox')
    
    builder = (
        Template()
        .from_ubuntu_image('22.04')
        .set_workdir('/app')
        .set_user('ubuntu:ubuntu')
        .set_envs({
            'DEBIAN_FRONTEND': 'noninteractive',
            'HOSTNAME': 'sandbox',
            'UV_INDEX_URL': 'https://mirrors.aliyun.com/pypi/simple/'
        })
        .run_cmd("sed -i 's|http://archive.ubuntu.com/ubuntu/|http://mirrors.aliyun.com/ubuntu/|g' /etc/apt/sources.list")
        .run_cmd("sed -i 's|http://security.ubuntu.com/ubuntu/|http://mirrors.aliyun.com/ubuntu/|g' /etc/apt/sources.list")
        .apt_install([
            'sudo', 'bc', 'curl', 'wget', 'gnupg', 'software-properties-common',
            'xvfb', 'x11vnc', 'xterm', 'socat', 'supervisor', 'websockify',
            'python3.10', 'python3.10-venv', 'python3.10-dev', 'python3-pip',
            'nodejs', 'chromium-browser', 'fonts-noto-cjk', 'fonts-noto-color-emoji',
            'language-pack-zh-hans', 'locales'
        ])
        .run_cmd('update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.10 1')
        .run_cmd('pip3 install uv')
        .run_cmd('npm config set registry https://registry.npmmirror.com')
        .run_cmd('locale-gen zh_CN.UTF-8')
        
        # Gunakan copy_items untuk menyalin beberapa item sekaligus
        .copy_items([
            {'src': 'pyproject.toml', 'dest': '/app/pyproject.toml'},
            {'src': 'app', 'dest': '/app/app'},
            {'src': 'start.sh', 'dest': '/app/start.sh'}
        ])
        
        .run_cmd('cd /app && uv sync --no-dev')
        .set_start_cmd('bash /app/start.sh', 'curl --fail http://localhost:8080/health || exit 1')
    )

    print("Membangun template di cloud E2B...")
    try:
        build_info = Template.build(
            builder,
            name='ai-manus-sandbox',
            api_key=api_key
        )
        print(f"Template berhasil dibangun! ID: {build_info.template_id}")
    except Exception as e:
        print(f"Gagal membangun template: {str(e)}")

if __name__ == "__main__":
    build_ai_manus_template()
