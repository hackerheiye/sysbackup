import subprocess
import os
import hashlib
from pathlib import Path

def obscure_password(password):
    """使用 rclone 命令行工具来加密密码"""
    rclone_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'rclone.exe')
    result = subprocess.run([rclone_path, 'obscure', password], capture_output=True, text=True, encoding='utf-8')
    if result.returncode == 0:
        return result.stdout.strip()
    else:
        raise ValueError("Failed to obscure password: " + result.stderr)

def run_rclone_command(args):
    """运行 rclone 命令并返回结果"""
    rclone_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'rclone.exe')  # 你可以在这里指定 rclone.exe 的完整路径
    try:
        result = subprocess.run([rclone_path] + args, capture_output=True, text=True, encoding='utf-8')
        result.check_returncode()
        return result
    except subprocess.CalledProcessError as e:
        print(f"rclone 命令执行失败: {e}")
        return None
    except FileNotFoundError:
        print(f"找不到 rclone.exe，请确保它在路径 {rclone_path} 中，或者添加到系统的 PATH 环境变量中。")
        return None

def load_config(config_path):
    """加载现有的配置文件"""
    if not os.path.exists(config_path):
        return None
    config = {}
    with open(config_path, "r") as config_file:
        lines = config_file.readlines()
    current_remote = None
    for line in lines:
        line = line.strip()
        if line and not line.startswith('#'):
            if line.startswith('[') and line.endswith(']'):
                current_remote = line[1:-1]
                config[current_remote] = {}
            elif '=' in line and current_remote:
                key, value = line.split('=', 1)
                config[current_remote][key.strip()] = value.strip()
    return config

def create_config(remote_name, config_data):
    """创建或更新 rclone 配置文件"""
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rclone.conf")
    if os.path.exists(config_path):
        response = input(f"配置文件 {config_path} 已存在。是否覆盖内容？(y/n): ")
        if response.lower() == 'y':
            with open(config_path, "w") as config_file:
                for name, data in config_data.items():
                    config_file.write(f"[{name}]\n")
                    for key, value in data.items():
                        config_file.write(f"{key} = {value}\n")
                    config_file.write("\n")
            print("配置文件已更新。")
        elif response.lower() == 'n':
            print("操作已取消。")
            return
    else:
        with open(config_path, "w") as config_file:
            for name, data in config_data.items():
                config_file.write(f"[{name}]\n")
                for key, value in data.items():
                    config_file.write(f"{key} = {value}\n")
                config_file.write("\n")
        print("配置文件已创建。")

def calculate_local_md5(path):
    """计算本地文件的 MD5 值"""
    md5_dict = {}
    for root, dirs, files in os.walk(path):
        for file in files:
            file_path = os.path.join(root, file)
            with open(file_path, 'rb') as f:
                md5 = hashlib.md5()
                while chunk := f.read(4096):
                    md5.update(chunk)
                md5_dict[file_path] = md5.hexdigest()
    return md5_dict

def get_remote_md5(remote_name, remote_path):
    """获取远程文件的 MD5 值"""
    result = run_rclone_command(['hashsum', 'MD5', remote_name + ':' + remote_path])
    if result is None or result.returncode != 0:
        return None
    output = result.stdout
    if not output or output.strip() == "":
        return {}
    remote_md5_dict = {}
    for line in output.split('\n'):
        if line:
            parts = line.split()
            if len(parts) >= 2:
                remote_md5_dict[parts[0]] = parts[1]
    return remote_md5_dict

def compare_and_backup(local_path, remote_name, remote_path, local_md5, remote_md5):
    """比较本地和远程文件的 MD5 值并备份不一致的文件"""
    if remote_md5 is None:
        print("远程目录为空，执行备份所有本地文件。")
        backup_cmd = ['copy', '--progress', local_path, f'{remote_name}:{remote_path}']
        run_rclone_command(backup_cmd)
        return

    for file_path, local_md5_value in local_md5.items():
        if file_path not in remote_md5 or remote_md5[file_path] != local_md5_value:
            print(f"文件 {file_path} 的 MD5 值不匹配，执行备份。")
            file_backup_cmd = ['copy', file_path, f'{remote_name}:{remote_path}']
            run_rclone_command(file_backup_cmd)
        else:
            print(f"文件 {file_path} 的 MD5 值匹配，跳过备份。")

def main():
    print("Rclone 备份工具")
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rclone.conf")
    config = load_config(config_path)

    if config:
        print("检测到现有配置，是否需要修改？(y/n):")
        response = input("输入 'y' 进行修改，输入 'n' 使用现有配置：")
        if response.lower() == 'y':
            # 用户选择修改配置
            remote_name = input("请输入远程存储的名称：")
            type = input("请输入远程存储的类型（例如，sftp等）：")
            host = input("请输入服务器 IP 或域名：")
            port = input("请输入端口号（如果不需要请直接按 Enter 跳过）：") or ""
            user = input("请输入您的账户：")
            password = input("请输入您的密码：")
            password_obscured = obscure_password(password)
            remote_path = input("请输入服务器上的目的地路径：")
            local_path = input("请输入需要备份的本地路径：")
            config_data = {remote_name: {
                'type': type,
                'host': host,
                'port': port,
                'user': user,
                'pass': password_obscured,
                'remote_path': remote_path
            }}
            create_config(remote_name, config_data)
        else:
            # 用户选择使用现有配置
            remote_name = next(iter(config))
            remote_config = config[remote_name]
            type = remote_config.get('type')
            host = remote_config.get('host')
            port = remote_config.get('port', '')
            user = remote_config.get('user')
            password = remote_config.get('pass')
            remote_path = remote_config.get('remote_path')
            local_path = input("请输入需要备份的本地路径：")
    else:
        # 没有现有配置，需要用户输入
        remote_name = input("请输入远程存储的名称：")
        type = input("请输入远程存储的类型（例如，sftp等）：")
        host = input("请输入服务器 IP 或域名：")
        port = input("请输入端口号（如果不需要请直接按 Enter 跳过）：") or ""
        user = input("请输入您的账户：")
        password = input("请输入您的密码：")
        password_obscured = obscure_password(password)
        remote_path = input("请输入服务器上的目的地路径：")
        local_path = input("请输入需要备份的本地路径：")
        config_data = {remote_name: {
            'type': type,
            'host': host,
            'port': port,
            'user': user,
            'pass': password_obscured,
            'remote_path': remote_path
        }}
        create_config(remote_name, config_data)

    # 计算本地文件的 MD5 值
    local_md5 = calculate_local_md5(local_path)

    # 获取远程文件的 MD5 值
    remote_md5 = get_remote_md5(remote_name, remote_path)

    # 比较并备份不一致的文件
    compare_and_backup(local_path, remote_name, remote_path, local_md5, remote_md5)

if __name__ == "__main__":
    main()
