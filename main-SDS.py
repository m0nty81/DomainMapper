import configparser
import ipaddress
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

import dns.resolver
import requests

# Function to load URLs from external file
def load_urls(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        lines = response.text.split('\n')
        urls = {}
        for line in lines:
            if line.strip():
                service, url = line.split(': ', 1)
                urls[service.strip()] = url.strip()
        return urls
    except Exception as e:
        print(f"Ошибка при загрузке списка платформ: {e}")
        return {}

# Load URLs from external file
platform_db_url = "https://raw.githubusercontent.com/Ground-Zerro/DomainMapper/main/platformdb.txt"
urls = load_urls(platform_db_url)

dns_servers = {
    'Системные': None,
    'Google': ['8.8.8.8', '8.8.4.4'],
    'Quad9': ['9.9.9.9', '149.112.112.112'],
    'OpenDNS': ['208.67.222.222', '208.67.220.220'],
    'Cloudflare': ['1.1.1.1', '1.0.0.1'],
    'CleanBrowsing': ['185.228.168.9', '185.228.169.9'],
    'Alternate DNS': ['76.76.19.19', '76.223.122.150'],
    'AdGuard DNS': ['94.140.14.14', '94.140.15.15']
}

# Function to resolve DNS
def resolve_dns_and_write(service, url, unique_ips_all_services, include_cloudflare, threads, cloudflare_ips_count,
                          null_ips_count, resolver_nameserver_pairs):
    try:
        print(f"\033[33mЗагрузка данных - {service}\033[0m")
        response = requests.get(url)
        response.raise_for_status()
        dns_names = response.text.split('\n')

        if include_cloudflare:
            cloudflare_ips = get_cloudflare_ips()
        else:
            cloudflare_ips = set()

        unique_ips_current_service = set()

        print(f"\033[33mАнализ DNS имен платформы: {service}\033[0m")

        with ThreadPoolExecutor(max_workers=threads) as executor:
            futures = []
            for nameserver_pair in resolver_nameserver_pairs:
                future = executor.submit(resolve_domains_with_nameservers, dns_names, unique_ips_current_service,
                                         unique_ips_all_services, cloudflare_ips, cloudflare_ips_count, null_ips_count,
                                         nameserver_pair)
                futures.append(future)

            for future in as_completed(futures):
                future.result()

        print(f"Список IP-адресов для платформы {service} создан.")
        return '\n'.join(unique_ips_current_service) + '\n'
    except Exception as e:
        print(f"Не удалось сопоставить IP адреса {service} его доменным именам.", e)
        return ""

# Function to get Cloudflare IP addresses
def get_cloudflare_ips():
    try:
        response = requests.get("https://www.cloudflare.com/ips-v4/")
        response.raise_for_status()
        cloudflare_ips = set()

        cidr_blocks = re.findall(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}/\d{1,2})', response.text)

        for cidr in cidr_blocks:
            ip_network = ipaddress.ip_network(cidr)
            for ip in ip_network:
                cloudflare_ips.add(str(ip))

        return cloudflare_ips
    except Exception as e:
        print("Ошибка при получении IP адресов Cloudflare:", e)
        return set()

# Function resolve domain using a pair of DNS servers
def resolve_domains_with_nameservers(domains, unique_ips_current_service, unique_ips_all_services, cloudflare_ips,
                                     cloudflare_ips_count, null_ips_count, nameservers):
    for domain in domains:
        domain = domain.strip()
        if domain:
            for nameserver in nameservers:
                resolver = dns.resolver.Resolver()
                resolver.nameservers = [nameserver]
                resolver.rotate = False
                resolver.timeout = 1
                resolver.lifetime = 1
                try:
                    ips = resolver.resolve(domain)
                    for ip in ips:
                        ip_address = ip.address
                        if ip_address in ('127.0.0.1', '0.0.0.0') or ip_address in resolver.nameservers:
                            null_ips_count[0] += 1
                        elif ip_address in cloudflare_ips:
                            cloudflare_ips_count[0] += 1
                        elif ip_address not in unique_ips_all_services:
                            unique_ips_current_service.add(ip_address)
                            unique_ips_all_services.add(ip_address)
                            print(f"\033[36m{domain} IP адрес: {ip_address} через DNS сервер: {nameserver}\033[0m")
                except Exception as e:
                    print(f"\033[31mНе удалось разрешить {domain} через DNS сервер {nameserver}: {e}\033[0m")

# Function to read configuration file
def read_config(filename):
    try:
        config = configparser.ConfigParser()
        with open(filename, 'r', encoding='utf-8-sig') as file:
            config.read_file(file)
        if 'DomainMapper' in config:
            config = config['DomainMapper']
        service = config.get('service') or ''
        threads = int(config.get('threads') or 20)
        filename = config.get('filename') or 'domain-ip-resolve.txt'
        cloudflare = config.get('cloudflare') or ''
        filetype = config.get('filetype') or ''
        gateway = config.get('gateway') or ''
        run_command = config.get('run') or ''

        print("Загружена конфигурация из config.ini.")
        return service, threads, filename, cloudflare, filetype, gateway, run_command

    except Exception as e:
        print(f"Ошибка загрузки конфигурации: {e}")
        return '', 20, 'domain-ip-resolve.txt', '', '', '', ''

def gateway_input(gateway):
    if not gateway:
        input_gateway = input(f"Укажите \033[32mшлюз\033[0m или \033[32mимя интерфейса\033[0m: ")
        if input_gateway:
            return input_gateway.strip()
    else:
        return gateway

# Function to check if 'service' is specified in the configuration file
def check_service_config(service):
    if service:
        if service.strip().lower() == "all":
            return list(urls.keys())
        else:
            return [s.strip() for s in service.split(',')]
    else:
        selected_services = []
        while True:
            if os.name == 'nt':
                os.system('cls')
            else:
                os.system('clear')
            print("\nВыберите сервисы:\n")
            for idx, (service, url) in enumerate(urls.items(), 1):
                print(f"{idx}. {service.capitalize()}")

            selection = input("\nУкажите номера сервисов через пробел и нажмите \033[32mEnter\033[0m: ")
            if selection.strip():
                selections = selection.split()
                selected_services = [list(urls.keys())[int(sel) - 1] for sel in selections if sel.isdigit()
                                     and 1 <= int(sel) <= len(urls)]
            break
        return selected_services

def check_include_cloudflare(cloudflare):
    if cloudflare.lower() == 'yes':
        return True
    elif cloudflare.lower() == 'no':
        return False
    else:
        return input("\nИсключить IP адреса Cloudflare из итогового списка? (\033[32myes\033[0m "
                     "- исключить, \033[32mEnter\033[0m - оставить): ").strip().lower() == "yes"

def check_dns_servers():
    system_dns_servers = dns.resolver.Resolver().nameservers
    selected_dns_servers = []

    while True:
        if os.name == 'nt':
            os.system('cls')
        else:
            os.system('clear')
        print("Какие DNS сервера использовать?\n")
        print(f"1. Системные: {', '.join(system_dns_servers)}")
        print("2. Google: 8.8.8.8 и 8.8.4.4")
        print("3. Quad9: 9.9.9.9 и 149.112.112.112")
        print("4. OpenDNS: 208.67.222.222 и 208.67.220.220")
        print("5. Cloudflare: 1.1.1.1 и 1.0.0.1")
        print("6. CleanBrowsing: 185.228.168.9 и 185.228.169.9")
        print("7. Alternate DNS: 76.76.19.19 и 76.223.122.150")
        print("8. AdGuard DNS: 94.140.14.14 и 94.140.15.15")

        selection = input("\nУкажите номера DNS серверов через пробел и нажмите \033[32mEnter\033[0m: ")
        if selection.strip():
            selections = selection.split()
            for sel in selections:
                if sel.isdigit():
                    sel = int(sel)
                    if sel == 1:
                        selected_dns_servers.extend(system_dns_servers)
                    elif sel == 2:
                        selected_dns_servers.extend(dns_servers['Google'])
                    elif sel == 3:
                        selected_dns_servers.extend(dns_servers['Quad9'])
                    elif sel == 4:
                        selected_dns_servers.extend(dns_servers['OpenDNS'])
                    elif sel == 5:
                        selected_dns_servers.extend(dns_servers['Cloudflare'])
                    elif sel == 6:
                        selected_dns_servers.extend(dns_servers['CleanBrowsing'])
                    elif sel == 7:
                        selected_dns_servers.extend(dns_servers['Alternate DNS'])
                    elif sel == 8:
                        selected_dns_servers.extend(dns_servers['AdGuard DNS'])
            break

    return [selected_dns_servers[i:i+2] for i in range(0, len(selected_dns_servers), 2)]

def process_file_format(filename, filetype, gateway):
    if not filetype:
        filetype = input("\nВыберите в каком формате сохранить файл: \n\033[32mwin\033[0m"
                         " - 'route add %IP% mask %mask% %gateway%', \033[32munix\033[0m"
                         " - 'ip route %IP%/%mask% %gateway%', \033[32mcidr\033[0m"
                         " - 'IP/mask', \033[32mEnter\033[0m - только IP: ")

    if filetype.lower() in ['win', 'unix']:
        gateway = gateway_input(gateway)

        try:
            with open(filename, 'r', encoding='utf-8-sig') as file:
                ips = file.readlines()
        except Exception as e:
            print(f"Ошибка чтения файла: {e}")
            return

        if ips:
            with open(filename, 'w', encoding='utf-8-sig') as file:
                for ip in ips:
                    if filetype.lower() == 'win':
                        file.write(f"route add {ip.strip()} mask 255.255.255.255 {gateway}\n")
                    elif filetype.lower() == 'unix':
                        file.write(f"ip route {ip.strip()}/32 {gateway}\n")
    elif filetype.lower() == 'cidr':
        try:
            with open(filename, 'r', encoding='utf-8-sig') as file:
                ips = file.readlines()
        except Exception as e:
            print(f"Ошибка чтения файла: {e}")
            return

        if ips:
            with open(filename, 'w', encoding='utf-8-sig') as file:
                for ip in ips:
                    file.write(f"{ip.strip()}/32\n")
    else:
        pass

def main():
    service, threads, filename, cloudflare, filetype, gateway, run_command = read_config('config.ini')

    total_resolved_domains = 0
    selected_services = check_service_config(service)
    resolver_nameserver_pairs = check_dns_servers()  # Get selected DNS server pairs
    include_cloudflare = check_include_cloudflare(cloudflare)

    unique_ips_all_services = set()
    cloudflare_ips_count = [0]  # To count the number of Cloudflare IPs excluded
    null_ips_count = [0]  # To count the number of null IPs excluded

    with open(filename, 'w', encoding='utf-8-sig') as file:
        for service in selected_services:
            result = resolve_dns_and_write(service, urls[service], unique_ips_all_services, include_cloudflare,
                                           threads, cloudflare_ips_count, null_ips_count, resolver_nameserver_pairs)
            file.write(result)
            total_resolved_domains += len(result.split('\n')) - 1

    print("\nПроверка завершена.")
    print(f"Использовались DNS сервера: {', '.join([', '.join(pair) for pair in resolver_nameserver_pairs])}")
    if include_cloudflare:
        print(f"Исключено IP-адресов Cloudflare: {cloudflare_ips_count[0]}")
    print(f"Исключено IP-адресов 'заглушек' провайдера: {null_ips_count[0]}")
    print(f"Разрешено IP-адресов из DNS списка: {total_resolved_domains}")

    process_file_format(filename, filetype, gateway)

    if run_command:
        print("\nВыполнение команды после завершения скрипта...")
        os.system(run_command)
    else:
        print("Результаты сохранены в файл:", filename)
        if os.name == 'nt':
            input("Нажмите \033[32mEnter\033[0m для выхода...")

if __name__ == "__main__":
    main()