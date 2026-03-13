#!/usr/bin/env python3
"""
Initialize PostgreSQL database with PGVector extension and schema.

Usage:
    python scripts/init_pgvector.py
    
Or with custom connection:
    python scripts/init_pgvector.py --host localhost --port 5432 --user postgres --password mypass --database genie_cache

This script will:
1. Create the database if it doesn't exist
2. Install the pgvector extension
3. Create the cached_queries table with vector column
4. Create indexes for efficient similarity search
"""

import asyncio
import argparse
import sys
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.storage_pgvector import PGVectorStorageService
from app.config import get_settings


async def init_database(connection_string: str, table_name: str = "cached_queries"):
    """Initialize the database with PGVector"""
    print("\nInitializing PostgreSQL database with PGVector...")
    print(f"   Connection: {connection_string.split('@')[1] if '@' in connection_string else connection_string}")
    print(f"   Table: {table_name}\n")
    
    try:
        # Create storage service
        storage = PGVectorStorageService(
            connection_string=connection_string,
            table_name=table_name
        )
        
        # Initialize (creates extension, table, and indexes)
        await storage.initialize()
        
        # Get and print stats
        stats = await storage.get_cache_stats()
        print(f"\nDatabase Statistics:")
        print(f"   Total queries: {stats['total_queries']}")
        print(f"   Unique identities: {stats['unique_identities']}")
        print(f"   Unique spaces: {stats['unique_spaces']}")
        
        # Close connection
        await storage.close()
        
        print("\nDatabase initialization complete!")
        return True
        
    except Exception as e:
        print(f"\nERROR: Error initializing database: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Initialize PostgreSQL database with PGVector extension"
    )
    parser.add_argument("--host", help="PostgreSQL host", default=None)
    parser.add_argument("--port", help="PostgreSQL port", type=int, default=None)
    parser.add_argument("--user", help="PostgreSQL user", default=None)
    parser.add_argument("--password", help="PostgreSQL password", default=None)
    parser.add_argument("--database", help="Database name", default=None)
    parser.add_argument("--table", help="Table name", default="cached_queries")
    
    args = parser.parse_args()
    
    # Get settings from environment or use provided args
    settings = get_settings()
    
    # Build connection string
    if args.host or args.port or args.user or args.password or args.database:
        # Use provided arguments
        host = args.host or settings.postgres_host
        port = args.port or settings.postgres_port
        user = args.user or settings.postgres_user
        password = args.password or settings.postgres_password
        database = args.database or settings.postgres_database
        
        connection_string = f"postgresql://{user}:{password}@{host}:{port}/{database}"
    else:
        # Use settings from environment
        connection_string = settings.postgres_connection_string
    
    # Run initialization
    success = asyncio.run(init_database(connection_string, args.table))
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
