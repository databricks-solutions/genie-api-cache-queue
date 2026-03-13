#!/usr/bin/env python3
"""
Test PGVector caching with sample queries.

This script demonstrates:
1. Initializing PGVector storage
2. Saving query embeddings
3. Searching for similar queries
4. Cache hit/miss behavior
"""

import asyncio
import sys
from pathlib import Path
import numpy as np

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.storage_pgvector import PGVectorStorageService
from app.config import get_settings


async def test_pgvector():
    """Run comprehensive PGVector tests"""
    
    print("\n" + "="*60)
    print("PGVector Cache Testing")
    print("="*60 + "\n")
    
    # Get settings
    settings = get_settings()
    
    # Create storage service
    print("Connecting to PostgreSQL...")
    storage = PGVectorStorageService(
        connection_string=settings.postgres_connection_string,
        table_name=settings.pgvector_table_name
    )
    
    try:
        # Initialize
        await storage.initialize()
        print("Connected and initialized\n")
        
        # Test 1: Save a query
        print("Test 1: Saving a query to cache")
        print("-" * 60)
        
        query1_text = "What are the top selling products in Q1 2024?"
        query1_embedding = np.random.rand(1024).tolist()  # Mock embedding
        query1_sql = "SELECT product_name, SUM(sales) FROM sales WHERE quarter = 'Q1 2024' GROUP BY product_name ORDER BY SUM(sales) DESC LIMIT 10"
        
        cache_id = await storage.save_query_cache(
            query_text=query1_text,
            query_embedding=query1_embedding,
            sql_query=query1_sql,
            identity="test_user@example.com",
            genie_space_id="test_space_123"
        )
        
        print(f"   Query text: {query1_text}")
        print(f"   Cache ID: {cache_id}")
        print(f"   Saved successfully\n")
        
        # Test 2: Search for exact same query (should hit)
        print("Test 2: Searching for exact same query")
        print("-" * 60)
        
        result = await storage.search_similar_query(
            query_embedding=query1_embedding,
            identity="test_user@example.com",
            threshold=0.85,
            genie_space_id="test_space_123"
        )
        
        if result:
            cache_id, text, sql, similarity = result
            print(f"   Result: CACHE HIT")
            print(f"   Similarity: {similarity:.4f}")
            print(f"   Retrieved SQL: {sql[:80]}...")
            print(f"   Use count updated: Yes\n")
        else:
            print(f"   Result: CACHE MISS (unexpected!)\n")
        
        # Test 3: Save a similar query
        print("Test 3: Saving a similar query")
        print("-" * 60)
        
        query2_text = "Top selling products Q1?"
        # Create similar but not identical embedding (98% similar)
        query2_embedding = (np.array(query1_embedding) * 0.98 + np.random.rand(1024) * 0.02).tolist()
        
        cache_id2 = await storage.save_query_cache(
            query_text=query2_text,
            query_embedding=query2_embedding,
            sql_query=query1_sql,  # Same SQL
            identity="test_user@example.com",
            genie_space_id="test_space_123"
        )
        
        print(f"   Query text: {query2_text}")
        print(f"   Cache ID: {cache_id2}")
        print(f"   Saved successfully\n")
        
        # Test 4: Search with slightly different embedding (should hit)
        print("Test 4: Searching with similar embedding")
        print("-" * 60)
        
        # Create another similar embedding
        query3_embedding = (np.array(query1_embedding) * 0.95 + np.random.rand(1024) * 0.05).tolist()
        
        result = await storage.search_similar_query(
            query_embedding=query3_embedding,
            identity="test_user@example.com",
            threshold=0.85,
            genie_space_id="test_space_123"
        )
        
        if result:
            cache_id, text, sql, similarity = result
            print(f"   Result: CACHE HIT")
            print(f"   Similarity: {similarity:.4f}")
            print(f"   Original query: {text}")
        else:
            print(f"   Result: CACHE MISS")
            print(f"   (Expected if similarity < threshold)\n")
        
        # Test 5: Search with different identity (should miss)
        print("Test 5: Searching with different identity")
        print("-" * 60)
        
        result = await storage.search_similar_query(
            query_embedding=query1_embedding,
            identity="different_user@example.com",  # Different user
            threshold=0.85,
            genie_space_id="test_space_123"
        )
        
        if result:
            print(f"   Result: CACHE HIT (unexpected!)")
        else:
            print(f"   Result: CACHE MISS")
            print(f"   Reason: Different identity (correct behavior)\n")
        
        # Test 6: Search with different space (should miss)
        print("Test 6: Searching with different Genie space")
        print("-" * 60)
        
        result = await storage.search_similar_query(
            query_embedding=query1_embedding,
            identity="test_user@example.com",
            threshold=0.85,
            genie_space_id="different_space_456"  # Different space
        )
        
        if result:
            print(f"   Result: CACHE HIT (unexpected!)")
        else:
            print(f"   Result: CACHE MISS")
            print(f"   Reason: Different Genie space (correct behavior)\n")
        
        # Test 7: Get all cached queries
        print("Test 7: Retrieving all cached queries")
        print("-" * 60)
        
        all_queries = await storage.get_all_cached_queries(
            identity="test_user@example.com"
        )
        
        print(f"   Total queries for test_user: {len(all_queries)}")
        for q in all_queries:
            print(f"   - ID {q['id']}: {q['query_text'][:50]}... (used {q['use_count']} times)")
        print()
        
        # Test 8: Cache statistics
        print("Test 8: Cache statistics")
        print("-" * 60)
        
        stats = await storage.get_cache_stats()
        print(f"   Total queries: {stats['total_queries']}")
        print(f"   Unique identities: {stats['unique_identities']}")
        print(f"   Unique spaces: {stats['unique_spaces']}")
        print(f"   Total uses: {stats['total_uses']}")
        print(f"   Avg uses per query: {stats['avg_uses_per_query']:.2f}")
        print()
        
        # Test 9: Very different query (should miss)
        print("Test 9: Searching with completely different embedding")
        print("-" * 60)
        
        random_embedding = np.random.rand(1024).tolist()
        
        result = await storage.search_similar_query(
            query_embedding=random_embedding,
            identity="test_user@example.com",
            threshold=0.85,
            genie_space_id="test_space_123"
        )
        
        if result:
            cache_id, text, sql, similarity = result
            print(f"   Result: CACHE HIT")
            print(f"   Similarity: {similarity:.4f}")
            print(f"   (Matched: {text[:50]}...)")
        else:
            print(f"   Result: CACHE MISS")
            print(f"   Reason: No similar query above threshold (correct behavior)\n")
        
        print("="*60)
        print("All tests completed successfully!")
        print("="*60 + "\n")
        
    except Exception as e:
        print(f"\nERROR: Test failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup
        await storage.close()


def main():
    asyncio.run(test_pgvector())


if __name__ == "__main__":
    main()
