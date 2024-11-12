import subprocess
import os
import hashlib
from pathlib import Path
import time
import logging
# 配置日志级别为 DEBUG
logging.basicConfig(filename=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'log.log'),
                    level=logging.DEBUG,
                    format='%(asctime)s - %(levelname)s - %(message)s')

def obscure_password(password):
    """使用 rclone 命令行工具来加密密码"""
    rclone_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'rclone.exe')
    result = subprocess.run([rclone_path, 'obscure', password], capture_output=True, text=True, encoding='utf-8')
    if result.returncode == 0:
        logging.info("密码加密成功。")
        return result.stdout.strip()
    else:
        logging.error("密码加密失败：" + result.stderr)
        raise ValueError("密码加密失败：" + result.stderr)

def run_rclone_command(args):
    """运行 rclone 命令并返回结果"""
    rclone_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'rclone.exe')
    try:
        result = subprocess.run([rclone_path] + args, capture_output=True, text=True, encoding='utf-8')
        result.check_returncode()
        logging.info("rclone 命令执行成功。")
        return result
    except subprocess.CalledProcessError as e:
        logging.error(f"rclone 命令执行失败：{e.returncode}，错误信息：{e.stderr}")
        return None
    except Exception as e:
        logging.error(f"运行 rclone 命令时发生异常：{e}")
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

def create_config(remote_name, config_data, append=False):
    """创建或更新 rclone 配置文件"""
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rclone.conf")
    if os.path.exists(config_path) and not append:
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
        with open(config_path, "a" if append else "w") as config_file:
            for name, data in config_data.items():
                if not config_file.tell():  # 如果文件是新创建的，不需要写入[]
                    config_file.write(f"[{name}]\n")
                for key, value in data.items():
                    config_file.write(f"{key} = {value}\n")
                config_file.write("\n")
    if append:
        print("配置文件已追加。")
    else:
        print("配置文件已创建。")
def ensure_remote_dirs(remote_name, local_path, remote_base_path):
    """确保远程目录结构与本地目录结构相匹配"""
    # 确保 local_path 是一个目录
    if not os.path.isdir(local_path):
        logging.error(f"提供的本地路径不是一个目录：{local_path}")
        return

    for root, dirs, files in os.walk(local_path):
        # 构建当前处理的远程目录路径
        remote_dir_path = os.path.normpath(os.path.join(remote_base_path, os.path.relpath(root, local_path)))
        
        # 确保路径以目录分隔符结尾
        if not remote_dir_path.endswith(os.sep):
            remote_dir_path += os.sep
        
        # 打印日志以调试路径问题
        logging.debug(f"正在检查远程目录: {remote_dir_path}")
        
        # 确保远程目录存在
        ensure_remote_dir_exists(remote_name, remote_dir_path)

        # 遍历所有文件，确保文件的父目录也被创建
        for file in files:
            local_file_path = os.path.join(root, file)
            file_dir_path = os.path.dirname(local_file_path)
            relative_file_dir_path = os.path.relpath(file_dir_path, local_path)
            remote_file_dir_path = os.path.normpath(os.path.join(remote_base_path, relative_file_dir_path))
            
            # 确保路径以目录分隔符结尾
            if not remote_file_dir_path.endswith(os.sep):
                remote_file_dir_path += os.sep
            
            # 打印日志以调试路径问题
            logging.debug(f"正在检查远程目录: {remote_file_dir_path}")
            
            # 确保远程目录存在
            ensure_remote_dir_exists(remote_name, remote_file_dir_path)

def ensure_remote_dir_exists(remote_name, remote_path):
    """确保远程目录存在，如果不存在则创建"""
    logging.debug("进入 ensure_remote_dir_exists 函数")
    
    # 确保路径以目录分隔符结尾
    if not remote_path.endswith(os.sep):
        remote_path = remote_path + os.sep

    # 打印远程路径以调试
    logging.debug(f"准备创建远程目录: {remote_path}")

    try:
        # 使用 rclone mkdir 命令创建远程目录
        result = run_rclone_command(['mkdir', f'{remote_name}:{remote_path}'])
        if result.returncode == 0:
            logging.info(f"远程目录 {remote_path} 已存在或已成功创建。")
        else:
            logging.error(f"创建远程目录 {remote_path} 失败：{result.stderr}")
    except Exception as e:
        logging.error(f"检查或创建远程目录时发生异常：{e}")
    finally:
        logging.debug("离开 ensure_remote_dir_exists 函数")

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
                md5_dict[md5.hexdigest()] = file_path
    return md5_dict

def get_remote_md5(remote_name, remote_path):
    """获取远程文件的 MD5 值"""
    if not remote_name or not remote_path:
        print("远程存储名称或路径为空。")
        return {}
    result = run_rclone_command(['hashsum', 'MD5', '--checksum', '--transfers=30', remote_name + ':' + remote_path])
    if result is None or result.returncode != 0:
        # 命令执行失败，返回一个空字典或执行其他操作
        print("无法获取远程文件的 MD5 值。")
        return {}
    output = result.stdout
    if not output.strip():
        print("远程路径可能不存在或为空。")
        return {}
    remote_md5_dict = {}
    for line in output.split('\n'):
        parts = line.split()
        if len(parts) >= 2:
            remote_md5_dict[parts[0]] = parts[1]  # Store the MD5 as key and the file path as value
    return remote_md5_dict

def compare_and_backup(local_path, remote_name, remote_base_path, local_md5, remote_md5):
    """比较本地和远程文件的 MD5 值并备份不一致的文件"""
    ensure_remote_dirs(remote_name, local_path, remote_base_path)  # 确保远程目录存在
    if remote_md5 is None:
        print("远程目录为空，执行备份所有本地文件。")
        backup_cmd = ['copy', '--progress', '--transfers=30', local_path, f'{remote_name}:{remote_base_path}']
        run_rclone_command(backup_cmd)
        return

    for local_md5_value, file_path in local_md5.items():
        if local_md5_value not in remote_md5:
            print(f"文件 MD5 值 {local_md5_value} 在远程不存在，执行备份。")
            # 获取文件的父目录路径
            file_dir_path = os.path.dirname(file_path)
            # 获取文件名
            file_name = os.path.basename(file_path)
            # 构建远程文件的父目录路径，不包含文件名
            remote_file_dir_path = os.path.normpath(os.path.join(remote_base_path, os.path.relpath(file_dir_path, local_path)))
            file_backup_cmd = ['copy', '--progress', '--transfers=30', file_path, f'{remote_name}:{remote_file_dir_path}']
            run_rclone_command(file_backup_cmd)
        else:
            print(f"文件 MD5 值 {local_md5_value} 匹配，跳过备份。")
def main():
    logging.info("备份工具开始运行。")
    print("备份工具")
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rclone.conf")
    config = load_config(config_path)

    # 如果存在现有配置，询问用户是否需要修改
    if config:
        print("检测到现有配置，是否需要修改？(y/n):")
        response = input("输入 'y' 进行修改，输入 'n' 使用现有配置：")
        if response.lower() == 'y':
            remote_name = input("请输入远程存储的名称：")
            type = input("请输入远程存储的类型（例如，sftp, dropbox, google drive 等）：")
            host = input("请输入服务器 IP 或域名：")
            port = input("请输入端口号（如果不需要请直接按 Enter 跳过）：") or ""
            user = input("请输入您的账户：")
            password = input("请输入您的密码：")
            password_obscured = obscure_password(password)
            remote_path = input("请输入服务器上的目的地路径：")  # 获取远程路径
            local_path = input("请输入需要备份的本地路径：")
            config_data = {remote_name: {
                'type': type,
                'host': host,
                'port': port,
                'user': user,
                'pass': password_obscured,
                'remote_path': remote_path
            }}
            create_config(remote_name, config_data, append=(response.lower() != 'y'))
        else:
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
        print("没有检测到现有配置，请输入配置信息：")
        remote_name = input("请输入远程存储的名称：")
        type = input("请输入远程存储的类型（例如，sftp, dropbox, google drive 等）：")
        host = input("请输入服务器 IP 或域名：")
        port = input("请输入端口号（如果不需要请直接按 Enter 跳过）：") or ""
        user = input("请输入您的账户：")
        password = input("请输入您的密码：")
        password_obscured = obscure_password(password)
        remote_path = input("请输入服务器上的目的地路径：")  # 获取远程路径
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
        logging.info("开始新的备份周期。")
        # 计算本地文件的 MD5 值
        local_md5 = calculate_local_md5(local_path)

        # 获取远程文件的 MD5 值
        remote_md5 = get_remote_md5(remote_name, remote_path)

        # 比较并备份不一致的文件
        compare_and_backup(local_path, remote_name, remote_path, local_md5, remote_md5)
        logging.info("开始新的备份周期。")
        # 计算本地文件的 MD5 值
        local_md5 = calculate_local_md5(local_path)

        # 获取远程文件的 MD5 值
        remote_md5 = get_remote_md5(remote_name, remote_path)

        # 比较并备份不一致的文件
        compare_and_backup(local_path, remote_name, remote_path, local_md5, remote_md5)
    while True:  # 创建一个无限循环
        logging.info("开始新的备份周期。")
        # 计算本地文件的 MD5 值
        local_md5 = calculate_local_md5(local_path)

        # 获取远程文件的 MD5 值
        remote_md5 = get_remote_md5(remote_name, remote_path)

        # 比较并备份不一致的文件
        compare_and_backup(local_path, remote_name, remote_path, local_md5, remote_md5)

        # 等待600秒（10分钟）后再次执行
        print("等待10分钟...")
        time.sleep(20)
        logging.info("备份周期完成，等待下一个周期。")

if __name__ == "__main__":
    main()
