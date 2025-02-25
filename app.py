from flask import Flask, render_template, request, flash, redirect, url_for, session
import pickle
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from collections import defaultdict

# Load the data
popular_df = pickle.load(open('popular.pkl', 'rb'))
pt = pickle.load(open('pt.pkl', 'rb'))
books = pickle.load(open('books.pkl', 'rb'))
similarity_scores = pickle.load(open('similarity_scores.pkl', 'rb'))
merged_books = pickle.load(open('merged_books.pkl', 'rb'))

app = Flask(__name__)
app.secret_key = 'your_secret_key'

# Database configuration
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Database models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)

class Favorite(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    book_title = db.Column(db.String(150), nullable=False)

class UserSearch(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    search_query = db.Column(db.String(150), nullable=False)

# Helper functions
def get_personalized_recommendations(user_id):
    user_searches = UserSearch.query.filter_by(user_id=user_id).order_by(UserSearch.id.desc()).all()
    recommendation_scores = defaultdict(float)
    recommended_titles = set()
    personalized_books = []

    # Assign weights based on the recency of each search
    for i, search in enumerate(user_searches):
        book_name = search.search_query.lower()
        weight = (1 / (i + 1)) ** 2  # More recent searches have higher weights
        matching_indices = {i for i, title in enumerate(pt.index) if book_name in title.lower()}
        exact_match_indices = {i for i, title in enumerate(pt.index) if title.lower() == book_name}
        matching_indices = list(matching_indices.union(exact_match_indices))

        if not matching_indices:
            continue

        for index in matching_indices:
            similar_items = enumerate(similarity_scores[index])
            for j, score in similar_items:
                title = pt.index[j]
                recommendation_scores[title] += weight * score  # Weight the score based on recency

    # Sort books by score, avoiding duplicates
    sorted_recommendations = sorted(recommendation_scores.items(), key=lambda x: x[1], reverse=True)

    for title, _ in sorted_recommendations:
        if title not in recommended_titles:
            recommended_titles.add(title)
            temp_df = books[books['Book-Title'] == title]
            if not temp_df.empty:
                personalized_books.append({
                    'title': title,
                    'author': temp_df['Book-Author'].values[0],
                    'image_url': temp_df['Image-URL-M'].values[0]
                })
            if len(personalized_books) >= 10:
                break

    return personalized_books


# Routes
@app.route('/')
def index():
    book_names = list(popular_df['Book-Title'].values)
    authors = list(popular_df['Book-Author'].values)
    images = list(popular_df['Image-URL-M'].fillna(url_for('static', filename='images/default-placeholder.jpg')).values)
    votes = list(popular_df['num_ratings'].values)
    ratings = list(popular_df['avg_rating'].values)

    # Create a mapping for book titles to ISBN
    isbn_map = {row['Book-Title']: row['ISBN'] for _, row in merged_books.iterrows()}

    return render_template('index.html',
                           book_name=book_names,
                           author=authors,
                           image=images,
                           votes=votes,
                           rating=ratings,
                           isbn=isbn_map)  # Pass the ISBN map to the template


@app.route('/book_detail/<string:book_title>')
def book_detail(book_title):
    # Find the book in the merged_books.pkl
    book_info = books[books['Book-Title'] == book_title].iloc[0]
    isbn = book_info['ISBN']
    google_books_url = f"https://books.google.com/books?vid=ISBN{isbn}"  # Google Books link
    return redirect(google_books_url)



@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = generate_password_hash(request.form['password'])

        if User.query.filter_by(username=username).first():
            flash("Username already exists.")
            return redirect(url_for('register'))

        new_user = User(username=username, password=password)
        db.session.add(new_user)
        db.session.commit()
        flash("Registration successful! Please log in.")
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            session['username'] = user.username
            flash("Login successful!")
            return redirect(url_for('index'))
        flash("Login failed. Check username and/or password.")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('username', None)
    flash("Logged out successfully.")
    return redirect(url_for('index'))

@app.route('/personalized')
def personalized():
    if 'user_id' not in session:
        flash("Please log in to view personalized recommendations.")
        return redirect(url_for('login'))

    user_id = session['user_id']
    personalized_books = get_personalized_recommendations(user_id)

    return render_template('personalized.html', personalized_books=personalized_books)

@app.route('/profile')
def profile():
    if 'user_id' not in session:
        flash("Please log in to view your profile.")
        return redirect(url_for('login'))

    favorites = Favorite.query.filter_by(user_id=session['user_id']).all()
    favorite_books = [fav.book_title for fav in favorites]
    return render_template('profile.html', favorites=favorite_books)

@app.route('/delete_profile', methods=['POST'])
def delete_profile():
    if 'user_id' not in session:
        flash("Please log in to delete your profile.")
        return redirect(url_for('login'))

    Favorite.query.filter_by(user_id=session['user_id']).delete()
    UserSearch.query.filter_by(user_id=session['user_id']).delete()
    user_to_delete = User.query.get(session['user_id'])

    if user_to_delete:
        db.session.delete(user_to_delete)
        db.session.commit()
        flash("Your profile has been deleted successfully.")
        session.pop('user_id', None)
        session.pop('username', None)
    else:
        flash("User not found.")

    return redirect(url_for('index'))

@app.route('/add_to_favorites/<string:book_title>')
def add_to_favorites(book_title):
    if 'user_id' not in session:
        flash("Please log in to add favorites.")
        return redirect(url_for('login'))

    existing_favorite = Favorite.query.filter_by(user_id=session['user_id'], book_title=book_title).first()
    if existing_favorite:
        flash(f"'{book_title}' is already in your favorites.")
    else:
        new_favorite = Favorite(user_id=session['user_id'], book_title=book_title)
        db.session.add(new_favorite)
        db.session.commit()
        flash(f"'{book_title}' added to favorites!")

    return redirect(url_for('profile'))

@app.route('/remove_from_favorites/<string:book_title>')
def remove_from_favorites(book_title):
    if 'user_id' not in session:
        flash("Please log in to remove favorites.")
        return redirect(url_for('login'))

    favorite_to_remove = Favorite.query.filter_by(user_id=session['user_id'], book_title=book_title).first()
    if favorite_to_remove:
        db.session.delete(favorite_to_remove)
        db.session.commit()
        flash(f"'{book_title}' removed from favorites!")
    else:
        flash(f"'{book_title}' is not in your favorites.")

    return redirect(url_for('profile'))

@app.route('/recommend')
def recommend_ui():
    return render_template('recommend.html')

@app.route('/recommend_books', methods=['POST'])
def recommend():
    user_input = request.form.get('user_input').strip()
    if not user_input:
        flash('Please enter a book title to get recommendations.')
        return redirect(url_for('recommend_ui'))

    book_name = ' '.join(user_input.split()).lower()
    matching_indices = [i for i, title in enumerate(pt.index) if book_name in title.lower()]
    exact_match_indices = [i for i, title in enumerate(pt.index) if title.lower() == book_name]
    matching_indices.extend(exact_match_indices)
    matching_indices = list(set(matching_indices))

    if not matching_indices:
        flash('No recommendations found for the given book title.')
        return redirect(url_for('recommend_ui'))

    similar_items = []
    for index in matching_indices:
        similar_items.extend(enumerate(similarity_scores[index]))

    similar_items = sorted(similar_items, key=lambda x: x[1], reverse=True)
    recommended_titles = []

    for i, score in similar_items:
        if pt.index[i] not in recommended_titles:
            recommended_titles.append(pt.index[i])
        if len(recommended_titles) >= 10:
            break

    if 'user_id' in session:
        user_id = session['user_id']
        user_search = UserSearch(user_id=user_id, search_query=user_input)
        db.session.add(user_search)
        db.session.commit()

    data = []
    for title in recommended_titles:
        temp_df = books[books['Book-Title'] == title]
        if not temp_df.empty:
            data.append({
                'title': title,
                'author': temp_df['Book-Author'].values[0],
                'image_url': temp_df['Image-URL-M'].values[0],
                'isbn': temp_df['ISBN'].values[0]  # Ensure ISBN is included
            })

    return render_template('recommend.html', recommended_books=data)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()  # Create database tables
    app.run(debug=True)