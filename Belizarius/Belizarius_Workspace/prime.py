def is_prime(n):
    if n <= 1:
        return False
    for i in range(2, int(n**0.5) + 1):
        if n % i == 0:
            return False
    return True

if __name__ == "__main__":
    # Display prime numbers up to 50
    primes = [n for n in range(2, 51) if is_prime(n)]
    print(f"Prime numbers up to 50: {primes}")
