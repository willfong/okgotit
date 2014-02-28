import sqlite3
import config

from flask import Flask, render_template, request, g, redirect, url_for
from twilio.rest import TwilioRestClient
from contextlib import closing

app = Flask(__name__)
app.config.from_object(__name__)

def connect_db():
  return sqlite3.connect(config.DATABASE)

def twilio_client():
  return TwilioRestClient(config.ACCOUNT_SID, config.AUTH_TOKEN)

def audit(msg):
  g.db.execute( "INSERT INTO log ( entrydate, entryip, entrylog ) VALUES ( DATETIME('now'), ?, ? )", [request.remote_addr, msg] )
  g.db.commit()

def calllog(msg):
  g.db.execute( "INSERT INTO log ( entrydate, entryip, entrylog ) VALUES ( DATETIME('now'), ?, ? )", [request.remote_addr, msg] )
  g.db.commit()

def grabuser(id):
  cur = g.db.execute('SELECT name, mobilenum FROM user WHERE id = ?', [id])
  row = cur.fetchall()
  return ( row[0][0], row[0][1] )

def grabgroup(id):
  cur = g.db.execute('SELECT name FROM callgroup WHERE id = ?', [id])
  row = cur.fetchall()
  return row[0][0]

@app.before_request
def before_request():
    g.db = connect_db()
    client = twilio_client()

@app.teardown_request
def teardown_request(exception):
    db = getattr(g, 'db', None)
    if db is not None:
        db.close()

@app.route("/")
def hello():
  return "Private Domain"

@app.route("/admin")
def admin():
  cur = g.db.execute('SELECT id, name FROM callgroup ORDER BY name')
  callgroups = [dict(id=row[0], name=row[1]) for row in cur.fetchall()]
  cur = g.db.execute('SELECT id, name, mobilenum FROM user ORDER BY name')
  users = [dict(id=row[0], name=row[1], mobilenum=row[2]) for row in cur.fetchall()]
  return render_template('admin.html', callgroups=callgroups, users=users)

@app.route("/log")
def logs():
  cur = g.db.execute('SELECT entrydate, entrylog FROM log ORDER BY id DESC LIMIT 50')
  entries = [dict(date=row[0], log=row[1]) for row in cur.fetchall()]
  return render_template('log.html', entries=entries)

@app.route("/users")
def users():
  cur = g.db.execute('SELECT id, name, mobilenum FROM user ORDER BY name')
  entries = [dict(id=row[0], name=row[1], mobilenum=row[2]) for row in cur.fetchall()]
  return render_template('users.html', entries=entries)

@app.route("/users/<id>")
def user(id=None):
  cur1 = g.db.execute('SELECT id, name, mobilenum FROM user WHERE id = ?', [id] )
  userid, username, usermobile = cur1.fetchone()
  cur2 = g.db.execute('SELECT cg.id, cg.name FROM callgroup AS cg INNER JOIN grouporder AS go ON cg.id = go.groupid WHERE go.userid = ? ORDER BY cg.name', [id] )
  callgroups = [dict(id=row2[0], name=row2[1]) for row2 in cur2.fetchall()]
  cur3 = g.db.execute('SELECT g.id, g.name, s1.id AS newevents, s2.id AS reminderevents FROM callgroup AS g LEFT JOIN smsnotify AS s1 ON g.id = s1.groupid AND s1.userid = ? AND s1.typeid = 1 LEFT JOIN smsnotify AS s2 ON g.id = s2.groupid AND s2.userid = ? AND s2.typeid = 2', [id, id] )
  smsnotify = [dict(groupid=row3[0], groupname=row3[1], newid=row3[2], reminderid=row3[3]) for row3 in cur3.fetchall()]
  userinfo = dict(id=userid, name=username, mobilenum=usermobile, callgroups=callgroups, smsnotify=smsnotify)
  return render_template('user.html', userinfo=userinfo)

@app.route("/users/add", methods=['POST'])
def adduser():
  g.db.execute('INSERT INTO user ( name, mobilenum ) VALUES ( ?, ? )', [request.form['name'], request.form['mobilenum']])
  g.db.commit()
  audit( "Added user: {} ({})".format( request.form['name'], request.form['mobilenum'] ) )
  return redirect(url_for('admin'))

@app.route("/users/<id>/del")
def deluser(id=None):
  name, mobilenum = grabuser(id)
  g.db.execute('DELETE FROM user WHERE id = ?', [id])
  g.db.execute('DELETE FROM grouporder WHERE userid = ?', [id])
  g.db.commit()
  audit( "Deleted User: {} ({})".format( name, mobilenum ) )
  return redirect(url_for('admin'))

@app.route("/users/<id>/addgroup/<gid>")
def addusertogroup(id=None,gid=None):
  g.db.execute('INSERT INTO grouporder ( groupid, userid ) VALUES ( ?, ? )', [gid, id])
  g.db.commit()
  username, mobilenum = grabuser(id)
  groupname = grabgroup(gid)
  audit( "Added {} ({}) to {}".format( username, mobilenum, groupname ) )
  return redirect(url_for('groups'))

@app.route("/users/<id>/removegroup/<gid>")
def removeuserfromgroup(id=None,gid=None):
  g.db.execute('DELETE FROM grouporder WHERE groupid = ? AND userid = ?', [gid, id])
  g.db.commit()
  username, mobilenum = grabuser(id)
  groupname = grabgroup(gid)
  audit( "Removed {} ({}) from {}".format( username, mobilenum, groupname ) )
  return redirect(url_for('groups'))

@app.route("/users/<id>/smsnotify/<action>/<type>/<gid>")
def modifysms(id=None, type=None, action=None, gid=None):

  if action == 'add':
    if type == 'new': typeid = 1
    if type == 'reminder': typeid = 2
    g.db.execute("INSERT INTO smsnotify ( userid, groupid, typeid ) VALUES ( ?, ?, ? )", [id, gid, typeid])
    g.db.commit()
    username, mobilenum = grabuser(id)
    groupname = grabgroup(gid)
    audit( "SMS Notification: Added {} ({}) to {} ({})".format( username, mobilenum, groupname, type ) )

  if action == 'remove':
    if type == 'new': typeid = 1
    if type == 'reminder': typeid = 2
    g.db.execute("DELETE FROM smsnotify WHERE userid = ? AND groupid = ? AND typeid = ?", [id, gid, typeid])
    g.db.commit()
    username, mobilenum = grabuser(id)
    groupname = grabgroup(gid)
    audit( "SMS Notification: Removed {} ({}) from {} ({})".format( username, mobilenum, groupname, type ) )

  return redirect(url_for('users')+'/'+id)

@app.route("/groups")
def groups():
  cur = g.db.execute('SELECT id, name FROM callgroup ORDER BY name')
  entries = []
  for row in cur.fetchall():
    id = row[0]
    name = row[1]
    cur1 = g.db.execute('SELECT u.id, u.name FROM user AS u LEFT JOIN grouporder AS go ON u.id = go.userid AND go.groupid = ? WHERE go.id IS NULL', [id])
    adduser = [dict(id=row[0], name=row[1]) for row in cur1.fetchall()]
    cur1 = g.db.execute('SELECT u.id, u.name FROM user AS u INNER JOIN grouporder AS go ON u.id = go.userid AND go.groupid = ?', [id])

    users = []
    prevuser = 0
    for row in cur1.fetchall():
      users.append(dict(id=row[0], name=row[1],prevuser=prevuser))
      prevuser = row[0]
    entries.append(dict(id=id,name=name,adduser=adduser,users=users))
  return render_template('groups.html',  entries=entries)

@app.route("/groups/add", methods=['POST'])
def addgroup():
  g.db.execute('INSERT INTO callgroup ( name ) VALUES ( ? )', [request.form['name']])
  g.db.commit()
  audit( "Created Group: {}".format(request.form['name']) )
  return redirect(url_for('admin'))

@app.route("/groups/<id>/del")
def delgroup(id=None):
  groupname = grabgroup(id)
  audit('Deleted Group: {}'.format(groupname))
  g.db.execute('DELETE FROM callgroup WHERE id = ?', [id])
  g.db.execute('DELETE FROM grouporder WHERE groupid = ?', [id])
  g.db.execute('DELETE FROM smsnotify WHERE groupid = ?', [id])
  g.db.commit()
  return redirect(url_for('admin'))

@app.route("/groups/<gid>/switch/<id>/<pid>")
def groupswitchuser(id=None,pid=None,gid=None):
  # Not sure I like this, but it works now...
  cur1 = g.db.execute('SELECT go.userid, go.id, cg.name FROM grouporder AS go INNER JOIN callgroup AS cg ON go.groupid = cg.id WHERE go.groupid = ? AND go.userid IN (?,?)', [gid, id, pid])
  rows = cur1.fetchall()
  g.db.execute('UPDATE grouporder SET userid = ? WHERE id = ?', [rows[0][0], rows[1][1]])
  g.db.execute('UPDATE grouporder SET userid = ? WHERE id = ?', [rows[1][0], rows[0][1]])
  g.db.commit()
  user1, mobilenum1 = grabuser(id)
  user2, mobilenum2 = grabuser(pid)
  audit( "Call Order Change: Moved {} ({}) above {} ({}) in {}".format( user1, mobilenum1, user2, mobilenum2, rows[0][2] ) )
  return redirect(url_for('groups'))

@app.route("/test/sms")
def testsms():
  client = TwilioRestClient(config.ACCOUNT_SID, config.AUTH_TOKEN)
  message = client.sms.messages.create(body="Reminder Action Alert! Check your email.", to=config.TEST_NUMBER, from_=config.TWILIO_NUMBER)
  return message.sid

@app.route("/test/postsms/<id>", methods=['POST'])
def testpostsms(id=None):
  message = "Ticket: {} Notes: {}".format(id, request.form['notes'])
  client = TwilioRestClient(config.ACCOUNT_SID, config.AUTH_TOKEN)
  message = client.sms.messages.create(body=message, to=config.TEST_NUMBER, from_=config.TWILIO_NUMBER)
  return message.sid


@app.route("/test/call")
def testcall():
  client = TwilioRestClient(config.ACCOUNT_SID, config.AUTH_TOKEN)
  # ...
  return message.sid

@app.route("/event/<id>/new", methods=['POST'])
def newticket(id=None):

  # Pondering the abuse of GET vs POST here...

  # For new tickets, we want to be very verbose. If there are any problems
  #  want to make it really easy to find out what steps got messed up.

  callgroup = request.form['callgroup']
  message = request.form['message']

  audit( "Received New Event: [{}] #{} {}".format( callgroup, id, message ) )

  cur = g.db.execute( 'SELECT id FROM callgroup WHERE name = ?', [callgroup])
  gid = cur.fetchone()

  # Check here if callgroup exists. Otherwise barf it back to whoever called us
  cur = g.db.execute('SELECT u.name, u.mobilenum FROM user AS u INNER JOIN smsnotify AS s ON u.id = s.userid AND s.groupid = ? AND s.typeid = 1', [gid[0]])
  contactlist = [dict(name=row[0], number=row[1]) for row in cur.fetchall()]

  if len(contactlist) > 0:

    printcontactlist = []
    for row in contactlist:
      printcontactlist.append( "{} ({})".format(row['name'], row['number']) )
    audit( "We will be sending an SMS to: {}".format( ', '.join(printcontactlist) ) )

    for row in contactlist:
      body = "New Ticket: {}".format( message )
      # For some reason, the global scope of 'client' doesn't work.
      # Investigate later.
      client = TwilioRestClient(config.ACCOUNT_SID, config.AUTH_TOKEN)
      message = client.sms.messages.create(body=body, to=row['number'], from_=config.TWILIO_NUMBER)
      audit( "SMS Sent to: {} ({}), code: {}".format( row['name'], row['number'], message.sid ) )


  # We need to have a monitoring process keep tabs on these
  #  calls. Doing all the call logic here has the potential
  #  of calls falling into cracks if something didn't work.
  # But finishing this project now is more important right
  #  now. Buyer beware!


  #xmlfile = "{}/xml/reminder".format( config.XMLURL )
  #call = client.calls.create(to=smsnum, from_=twilionumber, url=xmlfile)
  return 'SUCCESS'


@app.route("/xml/reminder", methods=['GET', 'POST'])
def reminder():
  return render_template('reminder.xml')

@app.route("/xml/response", methods=['GET', 'POST'])
def response():
  response = int(request.args.get('Digits', ''))
  return render_template('response.xml', response=response)

if __name__ == "__main__":
    app.debug = config.DEBUG
    app.run(host='0.0.0.0')
