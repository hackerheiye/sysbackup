import subprocess
import os
import hashlib
from pathlib import Path
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
# 配置日志
logging.basicConfig(filename=os.path.join(os.path.dirname(os.path.abspath(__file__)), 'log.log'),
                    level=logging.INFO,
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
        result.check_returncode()  # 这将引发 CalledProcessError 如果返回码非零
        logging.info("rclone 命令执行成功。\n标准输出:\n%s", result.stdout)
        return result
    except subprocess.CalledProcessError as e:
        logging.error("rclone 命令执行失败：返回状态码 %s。\n标准输出:\n%s\n标准错误输出:\n%s",
                      e.returncode, e.stdout, e.stderr)
        return None
    except Exception as e:
        logging.error("运行 rclone 命令时发生异常：%s", e)
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


def calculate_md5_for_file(file_path):
    """计算单个文件的 MD5 值"""
    with open(file_path, 'rb') as f:
        md5 = hashlib.md5()
        while chunk := f.read(4096):
            md5.update(chunk)
    return md5.hexdigest(), file_path

def calculate_local_md5(path):
    """并发计算本地文件的 MD5 值"""
    md5_dict = {}
    with ThreadPoolExecutor() as executor:
        future_to_file = {executor.submit(calculate_md5_for_file, os.path.join(root, file)): (root, file)
                          for root, _, files in os.walk(path) for file in files}
        for future in as_completed(future_to_file):
            root, file = future_to_file[future]
            try:
                md5_value, file_path = future.result()
                logging.info(f"本地文件MD5：{file_path} - {md5_value}")
            except Exception as exc:
                logging.error(f"{os.path.join(root, file)} 生成 MD5 时发生错误: {exc}")
            else:
                md5_dict[md5_value] = os.path.join(root, file)
    return md5_dict

def get_remote_md5(remote_name, remote_path):
    """获取远程文件的 MD5 值"""
    if not remote_name or not remote_path:
        logging.warning("远程存储名称或路径为空。")
        return {}
    logging.info("开始获取远程文件MD5...")
    result = run_rclone_command(['hashsum', 'MD5', '--transfers=16', remote_name + ':' + remote_path])
    if result is None or result.returncode != 0:
        logging.error("无法获取远程文件的 MD5 值。")
        return {}
    output = result.stdout
    if not output.strip():
        logging.warning("远程路径可能不存在或为空。")
        return {}
    remote_md5_dict = {}
    for line in output.split('\n'):
        parts = line.split()
        if len(parts) >= 2:
            md5_value = parts[0]
            file_path = os.path.join(remote_path, parts[1])  # Assuming the second part is the file name
            remote_md5_dict[md5_value] = file_path
            logging.info(f"远程文件MD5：{file_path} - {md5_value}")
    return remote_md5_dict

def compare_and_backup(local_path, remote_name, remote_path, local_md5, remote_md5):
    """比较本地和远程文件的 MD5 值并备份不一致的文件"""
    if remote_md5 is None:
        logging.info("远程目录为空，执行备份所有本地文件。")
        backup_cmd = ['copy', '--progress', '--transfers=10', local_path, f'{remote_name}:{remote_path}']
        run_rclone_command(backup_cmd)
        return

    for local_md5_value, local_file_path in local_md5.items():
        if local_md5_value not in remote_md5:
            logging.info(f"文件 MD5 值 {local_md5_value} 在远程不存在，执行备份：{local_file_path}")
            file_backup_cmd = ['copy', '--progress', '--transfers=10', local_file_path, f'{remote_name}:{remote_path}']
            result = run_rclone_command(file_backup_cmd)
            if result is not None and result.returncode == 0:
                logging.info(f"备份成功：{local_file_path}")
            else:
                logging.error(f"备份失败：{local_file_path}")
        else:
            logging.info(f"文件 MD5 值 {local_md5_value} 匹配，跳过备份：{local_file_path}")
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
        logging.info("开始新的备份周期。")
        # 计算本地文件的 MD5 值
        local_md5 = calculate_local_md5(local_path)

        # 获取远程文件的 MD5 值
        remote_md5 = get_remote_md5(remote_name, remote_path)

        # 比较并备份不一致的文件
        compare_and_backup(local_path, remote_name, remote_path, local_md5, remote_md5)

    try:
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
            time.sleep(32000)
            logging.info("备份周期完成，等待下一个周期。")
    except KeyboardInterrupt:
        logging.info("程序被用户中断。")
    finally:
        logging.info("程序结束运行。")

if __name__ == "__main__":
    main()
