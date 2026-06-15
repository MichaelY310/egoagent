# curl https://sh.rustup.rs -sSf | sh
cd /home/tiger/egoagent/meilisearch
cargo build --release 
./target/release/meilisearch --master-key="114514"