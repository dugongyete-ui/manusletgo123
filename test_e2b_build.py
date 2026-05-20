import os
from e2b import Template

def test_build():
    api_key = os.getenv("E2B_API_KEY")
    os.chdir('/home/ubuntu/ai-manus/sandbox')
    
    builder = (
        Template()
        .from_ubuntu_image('22.04')
        .run_cmd('echo "hello" > /hello.txt')
    )
    
    print("Membangun template tes...")
    build_info = Template.build(
        builder,
        name='test-template',
        api_key=api_key
    )
    print(f"Berhasil! ID: {build_info.template_id}")

if __name__ == "__main__":
    test_build()
