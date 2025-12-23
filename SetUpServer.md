# Set up temporary short living host

```sh
apt update
apt upgrade -y

# git
apt install -y git curl fio

# nvm
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash

export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"  # This loads nvm
[ -s "$NVM_DIR/bash_completion" ] && \. "$NVM_DIR/bash_completion"  # This loads nvm bash_completion

source /root/.bashrc

nvm install --lts

# docker
curl -fsSL https://get.docker.com | sh -

# pnpm
curl -fsSL https://get.pnpm.io/install.sh | sh -

source /root/.bashrc

# project
git clone https://github.com/damir-manapov/indexless-query-benchmarks.git
cd indexless-query-benchmarks
pnpm install
```
